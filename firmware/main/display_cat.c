/* display_cat.c - the room fills the whole glass, landscape, rotated on the CPU.
 *
 * Why the CPU: this DPI panel scans a fixed 720x1280 layout, so swap_xy tears the
 * picture (not rotate it), and the PPA only covers the bottom two thirds of a
 * 1280x720 input (its SRM block limit). A plain 90 degree copy is unambiguous.
 *
 * The animation model, which is the part that was wrong at first:
 *
 *   every frame, restore ALL rectangles drawn last frame from the static room,
 *   then draw - in painter's order - the things that sit on the floor (bowls,
 *   toy), then the cat (always on top), then anything over the cat (the heart),
 *   and finally push every touched rectangle through the rotation.
 *
 * Keeping the list is what makes things disappear: without it a bowl covers the
 * cat whenever their rectangles overlap, and a drawn heart stays on the glass for
 * ever because nothing ever repaints the pixels underneath it.
 */
#include "display_cat.h"

#include <stdlib.h>
#include <string.h>

#include "driver/ppa.h"
#include "esp_heap_caps.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_ops.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "assets.h"
#include "bsp/display.h"
#include "bsp/m5stack_tab5.h"

static const char *TAG = "display";

extern const uint8_t room_bin_start[]   asm("_binary_room_bin_start");
extern const uint8_t labels_bin_start[] asm("_binary_labels_bin_start");
extern const uint8_t sprites_bin_start[] asm("_binary_sprites_bin_start");
extern const uint8_t legend_bin_start[] asm("_binary_legend_bin_start");

#define DSI_W 720
#define DSI_H 1280
#define VIEW_W 1280
#define VIEW_H 720
#define FRAME CAT_FRAME                 /* 128 px sprite */
#define MAX_RECTS 10

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb[2];
static uint16_t *s_view;                /* landscape canvas */
static uint16_t *s_room;                /* the room at view size, never drawn on */
static uint16_t *s_ppa_out;             /* the DSI buffer we present */
static int s_fb_idx;
static bool s_flip;
static int s_fps, s_frames;
static int64_t s_fps_t0;

/* the rectangles touched last frame / this frame */
static int s_prev[MAX_RECTS][4], s_prev_n;
static int s_cur[MAX_RECTS][4], s_cur_n;

static inline void put(uint16_t *fb, int x, int y, uint16_t v) {
    if (x < 0 || y < 0 || x >= VIEW_W || y >= VIEW_H) return;
    fb[y * VIEW_W + x] = v;
}

static void add_rect(int x, int y, int w, int h) {
    if (s_cur_n >= MAX_RECTS) return;
    s_cur[s_cur_n][0] = x; s_cur[s_cur_n][1] = y;
    s_cur[s_cur_n][2] = w; s_cur[s_cur_n][3] = h;
    s_cur_n++;
}

static void restore_rect(uint16_t *fb, int x0, int y0, int w, int h) {
    if (!s_room) return;
    for (int j = 0; j < h; j++) {
        int y = y0 + j;
        if (y < 0 || y >= VIEW_H) continue;
        for (int i = 0; i < w; i++) {
            int x = x0 + i;
            if (x < 0 || x >= VIEW_W) continue;
            fb[y * VIEW_W + x] = s_room[y * VIEW_W + x];
        }
    }
}

/* Rotate one rectangle of the view into the portrait DSI buffer and push it.
 * s_flip only changes which way round the turn goes. */
static void rotate_rect(const uint16_t *fb, int vx0, int vy0, int w, int h) {
    if (vx0 < 0) { w += vx0; vx0 = 0; }
    if (vy0 < 0) { h += vy0; vy0 = 0; }
    if (vx0 + w > VIEW_W) w = VIEW_W - vx0;
    if (vy0 + h > VIEW_H) h = VIEW_H - vy0;
    if (w <= 0 || h <= 0) return;
    for (int vy = vy0; vy < vy0 + h; vy++) {
        const uint16_t *src = fb + (size_t)vy * VIEW_W;
        for (int vx = vx0; vx < vx0 + w; vx++) {
            int dx = s_flip ? (DSI_W - 1 - vy) : vy;
            int dy = s_flip ? vx : (VIEW_W - 1 - vx);
            s_ppa_out[(size_t)dy * DSI_W + dx] = src[vx];
        }
    }
    /* NO draw_bitmap here: presenting is once per frame. Doing it inside this
     * function meant 5-10 presents per frame (one per dirty rect), so the glass
     * showed half-updated states and the cat strobed (user: "猫一闪一闪的"). */
}

static void build_room(void) {
    s_room = heap_caps_malloc((size_t)VIEW_W * VIEW_H * 2, MALLOC_CAP_SPIRAM);
    if (!s_room) { ESP_LOGE(TAG, "no PSRAM for the room"); return; }
    const uint16_t *src = (const uint16_t *)room_bin_start;
    for (int y = 0; y < VIEW_H; y++) {
        const uint16_t *row = src + (y / 2) * CAT_ROOM_W;
        uint16_t *dst = s_room + y * VIEW_W;
        for (int x = 0; x < VIEW_W; x++) dst[x] = row[x / 2];
    }
    ESP_LOGI(TAG, "room built %dx%d from %dx%d", VIEW_W, VIEW_H, CAT_ROOM_W, CAT_ROOM_H);
}

static void draw_legend(uint16_t *fb) {
    const uint16_t *lg = (const uint16_t *)legend_bin_start;
    int lx = 16;
    int y = VIEW_H - CAT_LEGEND_H - 12;
    for (int i = 0; i < CAT_LEGEND_COUNT; i++) {
        const uint16_t *strip = lg + cat_legend_off[i];
        int w = cat_legend_w[i];
        for (int j = 0; j < CAT_LEGEND_H; j++)
            for (int k = 0; k < w; k++) {
                uint16_t v = strip[j * w + k];
                if (v) put(fb, lx + k, y + j, v);
            }
        lx += w + 18;
    }
}

bool display_cat_init(void) {
    if (bsp_i2c_init() != ESP_OK) { ESP_LOGE(TAG, "i2c bus failed"); return false; }
    if (bsp_feature_enable(BSP_FEATURE_LCD, true) != ESP_OK)
        ESP_LOGW(TAG, "the LCD's power (expander LCD_EN) did not switch");
    vTaskDelay(pdMS_TO_TICKS(200));

    const bsp_display_config_t cfg = {
        .dsi_bus = { .phy_clk_src = MIPI_DSI_PHY_CLK_SRC_DEFAULT,
                     .lane_bit_rate_mbps = BSP_LCD_MIPI_DSI_LANE_BITRATE_MBPS },
    };
    bsp_lcd_handles_t h = { 0 };
    if (bsp_display_new_with_handles(&cfg, &h) != ESP_OK || !h.panel) {
        ESP_LOGE(TAG, "the BSP could not bring the glass up: no picture");
        return false;
    }
    s_panel = h.panel;
    if (esp_lcd_dpi_panel_get_frame_buffer(s_panel, 2, (void **)&s_fb[0], (void **)&s_fb[1]) != ESP_OK) {
        ESP_LOGE(TAG, "no DSI frame buffers (CONFIG_BSP_LCD_DPI_BUFFER_NUMS must be 2)");
        return false;
    }
    s_view = heap_caps_malloc((size_t)VIEW_W * VIEW_H * 2, MALLOC_CAP_SPIRAM);
    s_ppa_out = s_fb[0];
    if (!s_view) { ESP_LOGE(TAG, "no PSRAM for the view"); return false; }
    build_room();
    if (s_room) {
        memcpy(s_view, s_room, (size_t)VIEW_W * VIEW_H * 2);
        draw_legend(s_view);
        rotate_rect(s_view, 0, 0, VIEW_W, VIEW_H);
    }
    bsp_display_brightness_set(80);
    s_fps_t0 = esp_timer_get_time();
    ESP_LOGI(TAG, "glass up: room %dx%d on a %dx%d portrait glass, cat %d px, legend %d px tall",
             VIEW_W, VIEW_H, DSI_W, DSI_H, FRAME, CAT_LEGEND_H);
    return true;
}

void display_cat_brightness(int pct) { bsp_display_brightness_set(pct); }
void display_cat_flip(bool on) { s_flip = on; }
bool display_cat_flipped(void) { return s_flip; }
/* the tap marker is gone: it was a debugging aid, not part of the cat */
void display_cat_mark(int vx, int vy) { (void)vx; (void)vy; }

static void draw_bowl(uint16_t *fb, float level, int cx, int cy, uint16_t colour) {
    restore_rect(fb, cx - 26, cy - 26, 52, 52);
    if (level < 0) level = 0;
    if (level > 1) level = 1;
    int hgt = (int)(20 * level);
    for (int j = 0; j < hgt; j++)
        for (int k = 0; k < 22; k++) put(fb, cx - 11 + k, cy + 10 - j, colour);
    add_rect(cx - 26, cy - 26, 52, 52);
}

static void fill(uint16_t *fb, int x, int y, int w, int h, uint16_t v) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++) put(fb, x + i, y + j, v);
}

/* a pre-rendered label, keyed on black (the exporter paints glyphs on black) */
static void blit_label(uint16_t *fb, const uint16_t *src, int w, int x, int y) {
    for (int j = 0; j < CAT_LABEL_H; j++)
        for (int i = 0; i < w; i++) {
            uint16_t v = src[j * w + i];
            if (v) put(fb, x + i, y + j, v);
        }
}

static bool s_show_panel;            /* the status panel is open */

void display_cat_toggle_panel(void) { s_show_panel = !s_show_panel; }
bool display_cat_panel_open(void) { return s_show_panel; }

/* The panel: one row per drive, with its pre-rendered Chinese label and a bar.
 * Numbers would need a font; bars carry the same information. */
static void draw_panel(uint16_t *fb, const cat_state_t *c) {
    const int x0 = 330, y0 = 140, w = 620, h = 440;
    fill(fb, x0, y0, w, h, 0x18E3);
    fill(fb, x0, y0, w, 4, 0x5AEB);
    fill(fb, x0, y0 + h - 4, w, 4, 0x5AEB);
    const uint16_t *lb = (const uint16_t *)labels_bin_start;
    /* the goal, at the top, boxed */
    int gi = c->goal_idx >= 0 ? c->goal_idx : CAT_LABEL_DRINK;
    blit_label(fb, lb + cat_label_off[gi], cat_label_w[gi], x0 + 24, y0 + 20);
    for (int i = 0; i < CAT_DRIVES; i++) {
        int y = y0 + 70 + i * 38;
        int idx = 9 + i;                       /* the 9 drive labels follow the goals */
        if (idx < CAT_LABEL_COUNT) blit_label(fb, lb + cat_label_off[idx], cat_label_w[idx], x0 + 24, y);
        int bx = x0 + 210;
        fill(fb, bx, y + 4, 340, 18, 0x2945);
        float v = c->drives[i] / 9.0f;
        if (v < 0) v = 0;
        if (v > 1) v = 1;
        fill(fb, bx, y + 4, (int)(340 * v), 18, 0x7FF0);
    }
    add_rect(x0, y0, w, h);
}

void display_cat_frame(const cat_state_t *c) {
    if (!s_panel || !s_view || !s_room) return;
    uint16_t *fb = s_view;

    /* 1. wipe everything drawn last frame, from the pristine room - AND push those
     * erased rectangles to the glass. Restoring only the canvas was the whole
     * reason the purr heart (and earlier, tap crosses) never disappeared: the pixel
     * change existed in s_view and never reached the DSI buffer. */
    for (int i = 0; i < s_prev_n; i++) {
        restore_rect(fb, s_prev[i][0], s_prev[i][1], s_prev[i][2], s_prev[i][3]);
        rotate_rect(fb, s_prev[i][0], s_prev[i][1], s_prev[i][2], s_prev[i][3]);
    }
    s_cur_n = 0;

    /* 2. the floor: what sits under the cat */
    draw_bowl(fb, c->food_left / 3.0f, 54 * 4, 128 * 4, 0xCB60);
    draw_bowl(fb, c->water_left / 3.0f, 104 * 4, 152 * 4, 0x4D5F);
    if (c->toy_wiggle > 0) {
        const int tx = 196 * 4, ty = 62 * 4;
        const int off = (c->toy_wiggle % 12 < 6) ? 10 : -10;
        restore_rect(fb, tx - 20, ty - 20, 60, 60);
        for (int j = -9; j <= 9; j++)
            for (int k = -9; k <= 9; k++)
                if (j * j + k * k <= 81) put(fb, tx + off + k, ty + j, 0xFE60);
        add_rect(tx - 20, ty - 20, 60, 60);
    }

    /* 3. the cat, always on top of the floor */
    int row, col;
    float hd = c->heading;
    if (c->purr_frames > 0)      { row = 2; col = 0; }               /* facing you */
    else if (c->asleep)          { row = 0; col = 3; }
    else if (c->moving)          { col = c->walking % 3;
                                   row = (hd < 45 || hd >= 315) ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); }
    else if (c->satisfied > 0)   { row = 2; col = (c->frame / 6) % 2; }  /* idle: looking about */
    else if (c->goal_idx >= 0 && (!strcmp(c->goal, "groom") || !strcmp(c->goal, "seek_food") ||
                                  !strcmp(c->goal, "drink")))
                                 { row = 4; col = (c->frame / 4) % 4; }
    else if (!c->moving)         { row = 4; col = (c->frame / 6) % 4; }  /* idle: grooming a paw */
    else                         { col = 0;
                                   row = (hd < 45 || hd >= 315) ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); }
    int cx = (int)(c->x * 4.0f) - FRAME / 2;
    int cy = (int)(c->y * 4.0f) - FRAME / 2;
    {
        const uint16_t *sheet = (const uint16_t *)sprites_bin_start;
        int stride = CAT_SHEET_COLS * FRAME;
        const uint16_t *frame = sheet + (row * FRAME) * stride + col * FRAME;
        for (int j = 0; j < FRAME; j++)
            for (int i = 0; i < FRAME; i++) {
                uint16_t v = frame[j * stride + i];
                if (v) put(fb, cx + i, cy + j, v);
            }
        add_rect(cx, cy, FRAME, FRAME);
    }

    /* 4. over the cat: the purr heart */
    if (c->purr_frames > 0) {
        const uint16_t *hb = (const uint16_t *)legend_bin_start + CAT_HEART_OFF;
        int hx = cx + FRAME / 2 - CAT_HEART / 2, hy = cy - CAT_HEART - 8;
        restore_rect(fb, hx - 2, hy - 2, CAT_HEART + 4, CAT_HEART + 4);
        for (int j = 0; j < CAT_HEART; j++)
            for (int k = 0; k < CAT_HEART; k++) {
                uint16_t v = hb[j * CAT_HEART + k];
                if (v) put(fb, hx + k, hy + j, v);
            }
        add_rect(hx - 2, hy - 2, CAT_HEART + 4, CAT_HEART + 4);
    }

    /* 4b. the status panel sits above everything while it is open */
    if (s_show_panel) draw_panel(fb, c);

    /* 5. push every touched rectangle, and remember them for the next wipe */
    for (int i = 0; i < s_cur_n; i++)
        rotate_rect(fb, s_cur[i][0], s_cur[i][1], s_cur[i][2], s_cur[i][3]);
    s_prev_n = s_cur_n;
    for (int i = 0; i < s_cur_n; i++)
        for (int k = 0; k < 4; k++) s_prev[i][k] = s_cur[i][k];

    /* 6. present ONCE per frame, after every rectangle has been written */
    esp_lcd_panel_draw_bitmap(s_panel, 0, 0, DSI_W, DSI_H, s_ppa_out);

    s_frames++;
    int64_t now = esp_timer_get_time();
    if (now - s_fps_t0 >= 1000000) {
        s_fps = s_frames; s_frames = 0; s_fps_t0 = now;
        ESP_LOGI(TAG, "cat %s at (%d,%d) cell %d,%d | %d rects | %d fps",
                 c->goal, cx, cy, row, col, s_cur_n, s_fps);
    }
}

int display_cat_fps(void) { return s_fps; }
