/* display_cat.c - the room fills the whole glass, landscape, via the PPA.
 *
 * The glass is 720x1280 portrait and its DPI engine scans that layout - changing
 * swap_xy did not rotate it, it just tore the picture (2026-10-17, my mistake).
 * The correct route on this board is the one pocket-tank uses: draw landscape into
 * a PSRAM buffer and let the PPA (pixel-processing accelerator) do the 90 degree
 * turn into the DSI frame buffer. Non-blocking, one frame behind, two buffers -
 * the PPA writes the buffer the DSI is not scanning.
 *
 * Room: 1280x720 = 4x the 320x180 logical grid, so the cat's sprites are 128 px.
 * The room is static, so it is upscaled once into s_room and each frame only puts
 * the cat's previous rectangle back before drawing the cat where it now is.
 */
#include "display_cat.h"

#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "driver/ppa.h"

#include "bsp/display.h"
#include "bsp/m5stack_tab5.h"
#include "assets.h"

static const char *TAG = "display";

extern const uint8_t room_bin_start[]    asm("_binary_room_bin_start");
extern const uint8_t sprites_bin_start[] asm("_binary_sprites_bin_start");

#define DSI_W 720                     /* what the glass scans */
#define DSI_H 1280
#define VIEW_W 1280                   /* what we draw (landscape) */
#define VIEW_H 720
#define FB_BYTES ((size_t)DSI_W * DSI_H * 2)
#define FRAME CAT_FRAME               /* 128 */

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb[2];
static uint16_t *s_view;              /* landscape drawing buffer */
static uint16_t *s_room;              /* the room at view size, built once */
static ppa_client_handle_t s_ppa;
static SemaphoreHandle_t s_ppa_done;
static uint16_t *s_ppa_out, *s_ppa_free;
static bool s_ppa_busy;
static int s_fps, s_frames;
static int64_t s_fps_t0;
static int s_last_cx = -1000, s_last_cy = -1000;

static inline void put(uint16_t *fb, int x, int y, uint16_t v) {
    if (x < 0 || y < 0 || x >= VIEW_W || y >= VIEW_H) return;
    fb[y * VIEW_W + x] = v;
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

static int blit_sprite(uint16_t *fb, const uint16_t *src, int dx, int dy, uint16_t key) {
    int painted = 0, stride = CAT_SHEET_COLS * FRAME;
    for (int j = 0; j < FRAME; j++) {
        int y = dy + j;
        if (y < 0 || y >= VIEW_H) continue;
        for (int i = 0; i < FRAME; i++) {
            uint16_t v = src[j * stride + i];
            if (v == key) continue;
            put(fb, dx + i, y, v);
            painted++;
        }
    }
    return painted;
}

/* Rotate one landscape rectangle of the view into the portrait DSI buffer.
 *
 * The DSI buffer persists between frames (the DPI engine scans it continuously),
 * so a frame only has to push the pixels that changed: the rectangle the cat just
 * left and the one it is about to occupy. A 90 degree turn maps a rectangle to a
 * rectangle, so that is the whole story - the full-frame copy it replaces cost
 * 12 fps. */
static void rotate_rect(const uint16_t *fb, int vx0, int vy0, int w, int h) {
    if (vx0 < 0) { w += vx0; vx0 = 0; }
    if (vy0 < 0) { h += vy0; vy0 = 0; }
    if (vx0 + w > VIEW_W) w = VIEW_W - vx0;
    if (vy0 + h > VIEW_H) h = VIEW_H - vy0;
    if (w <= 0 || h <= 0) return;
    for (int vy = vy0; vy < vy0 + h; vy++) {
        const uint16_t *src = fb + (size_t)vy * VIEW_W;
        for (int vx = vx0; vx < vx0 + w; vx++) {
            int dx = vy;                      /* landscape y -> portrait column */
            int dy = VIEW_W - 1 - vx;         /* flipped: the first mapping came out upside down */
            s_ppa_out[(size_t)dy * DSI_W + dx] = src[vx];
        }
    }
}

static bool ppa_done_cb(ppa_client_handle_t client, ppa_event_data_t *edata, void *user) {
    BaseType_t hp = pdFALSE;
    if (s_ppa_done) xSemaphoreGiveFromISR(s_ppa_done, &hp);
    return hp == pdTRUE;
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
    s_ppa_done = xSemaphoreCreateBinary();
    const ppa_client_config_t pc = { .oper_type = PPA_OPERATION_SRM, .max_pending_trans_num = 2 };
    if (!s_view || !s_ppa_done || ppa_register_client(&pc, &s_ppa) != ESP_OK) {
        ESP_LOGE(TAG, "no PPA client or no buffer");
        return false;
    }
    const ppa_event_callbacks_t cbs = { .on_trans_done = ppa_done_cb };
    ppa_client_register_event_callbacks(s_ppa, &cbs);
    s_ppa_out = s_fb[0]; s_ppa_free = s_fb[1]; s_ppa_busy = false;
    build_room();
    if (s_room) {
        /* the first frame is the whole room: everything later is a dirty rect, so
         * the DSI buffer has to start out complete or the rest stays noise */
        memcpy(s_view, s_room, (size_t)VIEW_W * VIEW_H * 2);
        rotate_rect(s_view, 0, 0, VIEW_W, VIEW_H);
        esp_lcd_panel_draw_bitmap(s_panel, 0, 0, DSI_W, DSI_H, s_ppa_out);
    }
    bsp_display_brightness_set(80);
    s_fps_t0 = esp_timer_get_time();
    ESP_LOGI(TAG, "glass up %dx%d portrait, drawn %dx%d landscape via PPA, cat %d px",
             DSI_W, DSI_H, VIEW_W, VIEW_H, FRAME);
    return true;
}

void display_cat_brightness(int pct) { bsp_display_brightness_set(pct); }

void display_cat_frame(const cat_state_t *c) {
    if (!s_panel || !s_view || !s_room) return;

    /* collect the previous frame's turn and hand it to the DSI */
    if (s_ppa_busy) {
        if (xSemaphoreTake(s_ppa_done, pdMS_TO_TICKS(200)) == pdTRUE) {
            s_ppa_busy = false;
            esp_lcd_panel_draw_bitmap(s_panel, 0, 0, DSI_W, DSI_H, s_ppa_out);
        }
    }

    uint16_t *fb = s_view;
    int row, col;
    float hd = c->heading;
    if (c->asleep)      { row = 0; col = 3; }
    else if (c->moving) { col = c->walking % 3;
                          row = (hd < 45 || hd >= 315) ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); }
    else if (c->goal_idx >= 0 && (!strcmp(c->goal, "groom") || !strcmp(c->goal, "seek_food") ||
                                  !strcmp(c->goal, "drink")))
                        { row = 4; col = (c->frame / 4) % 4; }
    else                { col = 0;
                          row = (hd < 45 || hd >= 315) ? 1 : (hd < 135 ? 0 : (hd < 225 ? 2 : 3)); }

    int cx = (int)(c->x * 4.0f) - FRAME / 2;      /* 320x180 grid -> 1280x720 */
    int cy = (int)(c->y * 4.0f) - FRAME / 2;
    if (s_last_cx > -999) restore_rect(fb, s_last_cx, s_last_cy, FRAME, FRAME);
    const uint16_t *sheet = (const uint16_t *)sprites_bin_start;
    int stride = CAT_SHEET_COLS * FRAME;
    int painted = blit_sprite(fb, sheet + (row * FRAME) * stride + col * FRAME, cx, cy, 0x0000);
    /* s_last_* may only move after the old rectangle has been rotated across, or
     * the "put the room back" call lands on the cat's NEW position and every
     * earlier position stays on the glass as a ghost cat */

    /* Turn the landscape view into the portrait DSI buffer here, on the CPU.
     *
     * The PPA was faster but only covered the bottom two thirds of a 1280x720
     * input (its SRM block is limited - pocket-tank's 720x405 input never hit it).
     * A plain 90 degree copy is unambiguous and always complete, and it is the
     * shape that matters most: a clean picture. The obvious optimisation for
     * later is to rotate only the cat's dirty rectangle, since the DSI buffer
     * persists between frames. */
    /* only the pixels that changed go across: where the cat was, where it is */
    if (s_last_cx > -999) rotate_rect(fb, s_last_cx, s_last_cy, FRAME, FRAME);
    rotate_rect(fb, cx, cy, FRAME, FRAME);
    s_last_cx = cx; s_last_cy = cy;
    esp_lcd_panel_draw_bitmap(s_panel, 0, 0, DSI_W, DSI_H, s_ppa_out);

    s_frames++;
    int64_t now = esp_timer_get_time();
    if (now - s_fps_t0 >= 1000000) {
        s_fps = s_frames; s_frames = 0; s_fps_t0 = now;
        ESP_LOGI(TAG, "cat %s at (%d,%d) cell %d,%d painted %d px | %d fps",
                 c->goal, cx, cy, row, col, painted, s_fps);
    }
}

int display_cat_fps(void) { return s_fps; }
