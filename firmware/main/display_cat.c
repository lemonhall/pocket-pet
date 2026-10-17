/* display_cat.c - the room fills the whole glass.
 *
 * Landscape 1280x720: the room's logical grid is 320x180, so the screen is exactly
 * 4x it and the cat's sprites are 32x4 = 128 px. There is no PPA and no rotation
 * math: esp_lcd_panel_swap_xy() makes the DPI engine scan the very same 1.84 MB
 * buffer as 1280x720, and we draw into it directly.
 *
 * Speed comes from the room being static: at init we upscale the 640x360 room
 * asset 2x into a PSRAM copy at screen size, and after that each frame only
 * repaints the cat's previous rectangle (from that copy) plus the cat itself -
 * no more blitting 921k pixels per frame.
 *
 * No status chrome: the user asked for a room with a cat in it, not a dashboard.
 * The drives and the current goal go to the console (status) and the log.
 */
#include "display_cat.h"

#include <string.h>

#include "esp_heap_caps.h"
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

#define PANEL_W 1280
#define PANEL_H 720
#define FRAME   CAT_FRAME              /* 128 */
#define GROUND   0x2104                /* what is left where the cat has been */

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_fb[2];
static uint16_t *s_room;              /* the room at screen size, built once */
static int s_fb_idx;
static int s_fps, s_frames;
static int64_t s_fps_t0;
static int s_last_cx = -1000, s_last_cy = -1000;

static inline void put(uint16_t *fb, int x, int y, uint16_t v) {
    if (x < 0 || y < 0 || x >= PANEL_W || y >= PANEL_H) return;
    fb[y * PANEL_W + x] = v;
}

/* the room asset (640x360) upscaled 2x into a screen-sized copy */
static void build_room(void) {
    s_room = heap_caps_malloc(PANEL_W * PANEL_H * 2, MALLOC_CAP_SPIRAM);
    if (!s_room) { ESP_LOGE(TAG, "no PSRAM for the room"); return; }
    const uint16_t *src = (const uint16_t *)room_bin_start;
    for (int y = 0; y < PANEL_H; y++) {
        const uint16_t *row = src + (y / 2) * CAT_ROOM_W;
        uint16_t *dst = s_room + y * PANEL_W;
        for (int x = 0; x < PANEL_W; x++) dst[x] = row[x / 2];
    }
    ESP_LOGI(TAG, "room built at %dx%d from %dx%d (2x)", PANEL_W, PANEL_H, CAT_ROOM_W, CAT_ROOM_H);
}

static void blit_room_rect(uint16_t *fb, int x0, int y0, int w, int h) {
    if (!s_room) return;
    for (int j = 0; j < h; j++) {
        int y = y0 + j;
        if (y < 0 || y >= PANEL_H) continue;
        for (int i = 0; i < w; i++) {
            int x = x0 + i;
            if (x < 0 || x >= PANEL_W) continue;
            fb[y * PANEL_W + x] = s_room[y * PANEL_W + x];
        }
    }
}

static int blit_sprite(uint16_t *fb, const uint16_t *src, int dx, int dy, uint16_t key) {
    int painted = 0;
    int stride = CAT_SHEET_COLS * FRAME;
    for (int j = 0; j < FRAME; j++) {
        int y = dy + j;
        if (y < 0 || y >= PANEL_H) continue;
        for (int i = 0; i < FRAME; i++) {
            uint16_t v = src[j * stride + i];
            if (v == key) continue;
            put(fb, dx + i, y, v);
            painted++;
        }
    }
    return painted;
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
    esp_lcd_panel_swap_xy(s_panel, true);          /* the glass is scanned landscape */
    if (esp_lcd_dpi_panel_get_frame_buffer(s_panel, 2, (void **)&s_fb[0], (void **)&s_fb[1]) != ESP_OK) {
        ESP_LOGE(TAG, "no DSI frame buffers (CONFIG_BSP_LCD_DPI_BUFFER_NUMS must be 2)");
        return false;
    }
    build_room();
    for (int i = 0; i < 2; i++) {
        if (!s_room) break;
        memcpy(s_fb[i], s_room, (size_t)PANEL_W * PANEL_H * 2);
        esp_lcd_panel_draw_bitmap(s_panel, 0, 0, PANEL_W, PANEL_H, s_fb[i]);
    }
    bsp_display_brightness_set(80);
    s_fps_t0 = esp_timer_get_time();
    ESP_LOGI(TAG, "glass up: %dx%d landscape, cat frame %d px, fb %p / %p",
             PANEL_W, PANEL_H, FRAME, s_fb[0], s_fb[1]);
    return true;
}

void display_cat_brightness(int pct) { bsp_display_brightness_set(pct); }

void display_cat_frame(const cat_state_t *c) {
    if (!s_panel || !s_room) return;
    uint16_t *fb = s_fb[s_fb_idx];
    s_fb_idx ^= 1;

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

    int cx = (int)(c->x * 4.0f) - FRAME / 2;      /* room grid 320x180 -> screen 4x */
    int cy = (int)(c->y * 4.0f) - FRAME / 2;

    /* put the room back where the cat was, then draw it where it is */
    if (s_last_cx > -999) blit_room_rect(fb, s_last_cx, s_last_cy, FRAME, FRAME);
    const uint16_t *sheet = (const uint16_t *)sprites_bin_start;
    int stride = CAT_SHEET_COLS * FRAME;
    const uint16_t *frame = sheet + (row * FRAME) * stride + col * FRAME;
    int painted = blit_sprite(fb, frame, cx, cy, 0x0000);
    s_last_cx = cx; s_last_cy = cy;

    esp_lcd_panel_draw_bitmap(s_panel, 0, 0, PANEL_W, PANEL_H, fb);
    s_frames++;
    int64_t now = esp_timer_get_time();
    if (now - s_fps_t0 >= 1000000) {
        s_fps = s_frames; s_frames = 0; s_fps_t0 = now;
        ESP_LOGI(TAG, "cat %s at (%d,%d) cell %d,%d painted %d px | %d fps",
                 c->goal, cx, cy, row, col, painted, s_fps);
    }
}

int display_cat_fps(void) { return s_fps; }
