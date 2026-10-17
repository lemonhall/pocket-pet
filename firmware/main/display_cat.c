/* display_cat.c - 720x1280 portrait, no rotation: the room is 640x360 (2x of the
 * Python renderer's 320x180) centred at the top, the status panel below it.
 *
 * There is no PPA here on purpose: the BSP hands us the DPI panel's own frame
 * buffers, we draw straight into them and tell the panel to present. That avoids
 * the tank's non-blocking-PPA dance entirely, at the cost of drawing in the
 * glass's native portrait orientation - which is what we want anyway, because the
 * status panel needs the vertical room.
 *
 * There is no font here either: every label is a pre-rendered RGB565 strip from
 * tools/export_cat_assets.py.
 */
#include "display_cat.h"

#include <string.h>

#include "esp_log.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "bsp/display.h"
#include "bsp/m5stack_tab5.h"
#include "assets.h"

static const char *TAG = "display";

extern const uint8_t room_bin_start[]    asm("_binary_room_bin_start");
extern const uint8_t sprites_bin_start[] asm("_binary_sprites_bin_start");
extern const uint8_t labels_bin_start[]  asm("_binary_labels_bin_start");

#define PANEL_W 720
#define PANEL_H 1280
#define ROOM_X 40
#define ROOM_Y 56
#define BAR_X  40
#define BAR_Y  (ROOM_Y + CAT_ROOM_H + 18)
#define BAR_W  420
#define BAR_H  18
#define BAR_GAP 6
#define GOAL_Y (BAR_Y + CAT_DRIVES * (BAR_H + BAR_GAP) + 14)

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb[2];
static int s_fb_idx;
static int s_fps, s_frames;
static int64_t s_fps_t0;

/* the drive bar colours, one per drive, in drive order */
static const uint16_t BAR_COLOR[CAT_DRIVES] = {
    0xFBE0, 0x5D9F, 0xFD20, 0xFC9F, 0xB5B6, 0x07FF, 0xFDA0, 0x8DD3, 0xC61F, 0x4DBF
};

static inline void put(uint16_t *fb, int x, int y, uint16_t v) {
    if (x < 0 || y < 0 || x >= PANEL_W || y >= PANEL_H) return;
    fb[y * PANEL_W + x] = v;
}

static void fill(uint16_t *fb, int x, int y, int w, int h, uint16_t v) {
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++) put(fb, x + i, y + j, v);
}

/* key == 0xFFFF means "opaque"; anything else is a colour key (transparent) */
static void blit(uint16_t *fb, const uint16_t *src, int sw, int sh, int dx, int dy, uint16_t key) {
    for (int j = 0; j < sh; j++) {
        int y = dy + j;
        if (y < 0 || y >= PANEL_H) continue;
        for (int i = 0; i < sw; i++) {
            uint16_t v = src[j * sw + i];
            if (key != 0xFFFF && v == key) continue;
            put(fb, dx + i, y, v);
        }
    }
}

bool display_cat_init(void) {
    if (bsp_i2c_init() != ESP_OK) { ESP_LOGE(TAG, "i2c bus failed"); return false; }
    /* the LCD's power rail lives on the IO expander: without it the glass is mute */
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
    bsp_display_brightness_set(80);
    s_fps_t0 = esp_timer_get_time();
    ESP_LOGI(TAG, "glass up: %dx%d, fb %p / %p, room %dx%d at (%d,%d)",
             PANEL_W, PANEL_H, s_fb[0], s_fb[1], CAT_ROOM_W, CAT_ROOM_H, ROOM_X, ROOM_Y);
    return true;
}

void display_cat_brightness(int pct) { bsp_display_brightness_set(pct); }

static void draw_cat(uint16_t *fb, const cat_state_t *c) {
    const uint16_t *sheet = (const uint16_t *)sprites_bin_start;
    int f = CAT_FRAME;
    int cols = CAT_SHEET_COLS;
    int row, col;
    float hd = c->heading;
    if (c->asleep)                       { row = 0; col = 3; }
    else if (c->moving)                  { col = c->walking % 3; row = hd < 45 || hd >= 315 ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); }
    else if (c->goal_idx >= 0 && (!strcmp(c->goal, "groom") || !strcmp(c->goal, "seek_food") || !strcmp(c->goal, "drink")))
                                         { row = 4; col = (c->frame / 4) % 4; }
    else                                 { row = hd < 45 || hd >= 315 ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); col = 0; }
    int sx = col * f, sy = row * f;
    const uint16_t *frame = sheet + (sy * (cols * f) + sx);
    int dx = ROOM_X + (int)(c->x * 2.0f) - f / 2;
    int dy = ROOM_Y + (int)(c->y * 2.0f) - f / 2;
    blit(fb, frame, f, f, dx, dy, 0x0000);        /* black is the sprite's transparency */
}

static void draw_status(uint16_t *fb, const cat_state_t *c) {
    const uint16_t *labels = (const uint16_t *)labels_bin_start;
    for (int i = 0; i < CAT_DRIVES; i++) {
        int y = BAR_Y + i * (BAR_H + BAR_GAP);
        const uint16_t *lbl = labels + cat_label_off[i + CAT_GOALS];
        blit(fb, lbl, cat_label_w[i + CAT_GOALS], CAT_LABEL_H, BAR_X, y, 0xFFFF);
        int bx = BAR_X + 96;
        fill(fb, bx, y + 2, BAR_W, BAR_H, 0x2104);
        float v = c->drives[i] / 9.0f;
        if (v > 1) v = 1;
        fill(fb, bx, y + 2, (int)(BAR_W * v), BAR_H, BAR_COLOR[i]);
    }
    /* the eight goals the model chooses from; the current one is boxed */
    for (int i = 0; i < CAT_GOALS; i++) {
        const uint16_t *lbl = labels + cat_label_off[i];
        int w = cat_label_w[i];
        int x = BAR_X + i * 150;
        int y = GOAL_Y + (i / 4) * 34;
        if (c->goal_idx == i) {
            fill(fb, x - 4, y - 4, w + 8, CAT_LABEL_H + 8, 0x39E7);
        }
        blit(fb, lbl, w, CAT_LABEL_H, x, y, 0xFFFF);
    }
    if (c->goal_idx < 0) fill(fb, BAR_X - 4, GOAL_Y + 68 - 4, 460, CAT_LABEL_H + 8, 0x39E7);
}

void display_cat_frame(const cat_state_t *c) {
    if (!s_panel) return;
    uint16_t *fb = s_fb[s_fb_idx];
    s_fb_idx ^= 1;
    blit(fb, (const uint16_t *)room_bin_start, CAT_ROOM_W, CAT_ROOM_H, ROOM_X, ROOM_Y, 0xFFFF);
    draw_cat(fb, c);
    draw_status(fb, c);
    esp_lcd_panel_draw_bitmap(s_panel, 0, 0, PANEL_W, PANEL_H, fb);
    s_frames++;
    int64_t now = esp_timer_get_time();
    if (now - s_fps_t0 >= 1000000) {
        s_fps = s_frames;
        s_frames = 0;
        s_fps_t0 = now;
    }
}

int display_cat_fps(void) { return s_fps; }
