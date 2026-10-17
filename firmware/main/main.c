/* main.c - the cat, on the Tab5.
 *
 * Three things live here:
 *   1. the brain: pocket-tank's q4_model.c + word_tok.c (vendor/llm, unmodified)
 *      reading build/cat_q4.bin from the model partition, asked once every four
 *      seconds which of its eight goals to pursue;
 *   2. the world: cat_world.c drifts the drives and walks the cat, at 20 fps, and
 *      a reflex layer overrides the model when the cat is thirsty (see
 *      cat_world.h for why thirst is not in the model's state line);
 *   3. the room: display_cat.c draws 720x1280 portrait - the room on top, the
 *      drives and the eight goals below.
 *
 * Console (the tank's director style, one command per interaction):
 *   food | water | play | pet | clean        what you do to the cat
 *   status                                   every drive + the current goal
 *   cat <state line>                         ask the brain directly
 *   bench [n] | dotcheck | info               the engine's own instruments
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_console.h"

#include "q4_model.h"
#include "word_tok.h"
#include "bsp/touch.h"
#include "driver/i2c_master.h"
#include "nvs.h"
#include "bsp/m5stack_tab5.h"
#include "esp_lcd_touch.h"

#include "cat_world.h"
#include "display_cat.h"

static const char *TAG = "cat";

extern const uint8_t cat_tok_bin_start[] asm("_binary_cat_tok_bin_start");
extern const uint8_t cat_tok_bin_end[]   asm("_binary_cat_tok_bin_end");

#define CAT_VOCAB 53
#define BRAIN_PERIOD_MS 4000
#define FRAME_MS 50              /* 20 fps */

static q4_model_t *s_model;
static word_tok_t  s_tok;
static int         s_goal_id[CAT_GOALS];
static uint32_t    s_rng = 0x1234567u;
static cat_state_t s_cat;
static volatile int s_decisions;

static void *psram_alloc(size_t n) {
    void *p = heap_caps_malloc(n, MALLOC_CAP_SPIRAM);
    return p ? p : malloc(n);
}

static int goal_id_of(const char *name) {
    int t[8];
    int n = word_tok_encode(&s_tok, name, t, 8);
    return n > 1 ? t[1] : -1;
}

/* defined further down, next to the RTC and nvs code */
static const char *rtc_tod(void);
static void save_state(void);
static int cmd_flip(int argc, char **argv);
static int cmd_help(int argc, char **argv);
static int cmd_tap(int argc, char **argv);

static void load_brain(void) {
    const esp_partition_t *mp = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, 0x40, NULL);
    if (!mp) { ESP_LOGE(TAG, "no model partition"); return; }
    const void *map = NULL; esp_partition_mmap_handle_t h;
    if (esp_partition_mmap(mp, 0, mp->size, ESP_PARTITION_MMAP_DATA, &map, &h) != ESP_OK) {
        ESP_LOGE(TAG, "mmap failed"); return;
    }
    q4_fast_alloc = psram_alloc;
    q4_clock_us = esp_timer_get_time;
    s_model = q4_model_open((const uint8_t *)map, mp->size, psram_alloc);
    if (!s_model) {
        uint32_t magic = 0; memcpy(&magic, map, 4);
        ESP_LOGE(TAG, "q4_model_open failed (magic 0x%08x, want 0x616b3432)", (unsigned)magic);
        return;
    }
    if (word_tok_init(&s_tok, cat_tok_bin_start,
                      (size_t)(cat_tok_bin_end - cat_tok_bin_start), CAT_VOCAB) != 0) {
        ESP_LOGE(TAG, "tokenizer init failed"); s_model = NULL; return;
    }
    for (int i = 0; i < CAT_GOALS; i++) s_goal_id[i] = goal_id_of(cat_goal_names[i]);
    const q4_config_t *c = q4_model_config(s_model);
    ESP_LOGI(TAG, "brain ready: dim %d hidden %d layers %d vocab %d seq %d | goals %d..%d",
             c->dim, c->hidden_dim, c->n_layers, c->vocab_size, c->seq_len,
             s_goal_id[0], s_goal_id[CAT_GOALS - 1]);
}

/* Ask the brain, restricted to its eight goals. Returns the goal name. */
static const char *ask_brain(void) {
    if (!s_model) return NULL;
    char line[256];
    cat_state_line(&s_cat, line, sizeof line);
    int toks[64];
    int n = word_tok_encode(&s_tok, line, toks, 64);
    if (n < 2) return NULL;
    float probs[CAT_GOALS];
    int out[2];
    int nout = q4_model_decide(s_model, toks, n, s_goal_id, CAT_GOALS, 0.0f, &s_rng, probs, out, 1);
    if (nout < 1) return NULL;
    for (int i = 0; i < CAT_GOALS; i++) if (s_goal_id[i] == out[0]) return cat_goal_names[i];
    return NULL;
}

static void brain_task(void *arg) {
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(BRAIN_PERIOD_MS));
        int64_t t0 = esp_timer_get_time();
        const char *g = ask_brain();
        int ms = (int)((esp_timer_get_time() - t0) / 1000);
        if (g) {
            s_decisions++;
            ESP_LOGI(TAG, "brain[%d]: %s -> %s (%d ms)", s_decisions, s_cat.last, g, ms);
            /* The reflex layer may not veto the model, only pre-empt it briefly:
             * a permanent veto meant a cat stuck at an empty bowl ignored every
             * "go eat" the brain ever produced (seen on the device 2026-10-17). */
            if (s_cat.drives[CAT_THIRST] < 6.0f || s_cat.snooze_frames > 0)
                cat_world_set_goal(&s_cat, g);
        } else {
            ESP_LOGW(TAG, "the brain did not answer (%d ms)", ms);
        }
        const char *t = rtc_tod();
        if (t) s_cat.tod = t;
        if ((s_decisions % 3) == 0) save_state();
        ESP_LOGI(TAG, "cat: hunger %d energy %d bored %d litter %d thirst %d | goal %s | time %s | %d fps",
                 (int)s_cat.drives[CAT_HUNGER], (int)s_cat.drives[CAT_ENERGY],
                 (int)s_cat.drives[CAT_BORED], (int)s_cat.drives[CAT_LITTER],
                 (int)s_cat.drives[CAT_THIRST], s_cat.goal, s_cat.tod, display_cat_fps());
    }
}

static void render_task(void *arg) {
    int64_t last = esp_timer_get_time();
    while (1) {
        int64_t now = esp_timer_get_time();
        float dt = (float)(now - last) / 1e6f;
        last = now;
        if (dt > 0.5f) dt = 0.5f;
        cat_world_tick(&s_cat, dt);
        display_cat_frame(&s_cat);
        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));
    }
}

/* ---- the things you can do to the cat ---- */
static void report(const char *what) {
    printf("%s: %s\n", what, s_cat.notice);
    printf("  hunger %d energy %d bored %d clingy %d litter %d curiosity %d bold %d lazy %d scruff %d thirst %d\n",
           (int)s_cat.drives[CAT_HUNGER], (int)s_cat.drives[CAT_ENERGY], (int)s_cat.drives[CAT_BORED],
           (int)s_cat.drives[CAT_CLINGY], (int)s_cat.drives[CAT_LITTER], (int)s_cat.drives[CAT_CURIOSITY],
           (int)s_cat.drives[CAT_BOLD], (int)s_cat.drives[CAT_LAZY], (int)s_cat.drives[CAT_SCRUFF],
           (int)s_cat.drives[CAT_THIRST]);
    printf("  goal %s | food %d water %d box %s | %d fps\n",
           s_cat.goal, (int)s_cat.food_left, (int)s_cat.water_left,
           s_cat.box_clean ? "clean" : "dirty", display_cat_fps());
}
#define CMD(fn, name) static int fn(int argc, char **argv) { (void)argc; (void)argv; fn##_do(); report(#name); return 0; }
static void food_do(void)  { cat_feed(&s_cat); }
static void water_do(void) { cat_water(&s_cat); }
static void play_do(void)  { cat_play_with(&s_cat); }
static void pet_do(void)   { cat_pet(&s_cat); }
static void clean_do(void) { cat_clean_box(&s_cat); }
CMD(food, food) CMD(water, water) CMD(play, play) CMD(pet, pet) CMD(clean, clean)

static int cmd_status(int argc, char **argv) {
    (void)argc; (void)argv;
    char line[256];
    cat_state_line(&s_cat, line, sizeof line);
    printf("notice: %s\n%s\n", s_cat.notice, line);
    report("status");
    return 0;
}

static int cmd_cat(int argc, char **argv) {
    if (!s_model) { printf("no model loaded\n"); return 1; }
    char line[256] = {0};
    for (int i = 1; i < argc; i++) {
        if (i > 1) strncat(line, " ", sizeof line - strlen(line) - 1);
        strncat(line, argv[i], sizeof line - strlen(line) - 1);
    }
    if (!line[0]) { printf("usage: cat hunger 6 energy 3 ... time night\n"); return 1; }
    int toks[64];
    int n = word_tok_encode(&s_tok, line, toks, 64);
    float probs[CAT_GOALS]; int out[2];
    int64_t t0 = esp_timer_get_time();
    int nout = q4_model_decide(s_model, toks, n, s_goal_id, CAT_GOALS, 0.0f, &s_rng, probs, out, 1);
    int ms = (int)((esp_timer_get_time() - t0) / 1000);
    if (nout < 1) { printf("no answer\n"); return 1; }
    const char *pick = "?";
    for (int i = 0; i < CAT_GOALS; i++) if (s_goal_id[i] == out[0]) pick = cat_goal_names[i];
    printf("-> %s (%d ms, %d prompt tokens)\n  p:", pick, ms, n);
    for (int i = 0; i < CAT_GOALS; i++) printf(" %s %.2f", cat_goal_names[i], probs[i]);
    printf("\n");
    return 0;
}

static int cmd_bench(int argc, char **argv) {
    if (!s_model) { printf("no model loaded\n"); return 1; }
    int n = argc > 1 ? atoi(argv[1]) : 8;
    int64_t us = q4_model_bench(s_model, 0, n, esp_timer_get_time);
    if (us <= 0) { printf("bench failed\n"); return 1; }
    printf("bench: %d tokens in %lld us = %.2f tok/s\n", n, (long long)us, (double)n * 1e6 / (double)us);
    return 0;
}

static int cmd_dotcheck(int argc, char **argv) {
    (void)argc; (void)argv;
    int r = q4_model_dot_check();
    printf("dotcheck: %s\n", r == -1 ? "the PIE dot matches the scalar dot" : "MISMATCH");
    return r == -1 ? 0 : 1;
}

static int cmd_info(int argc, char **argv) {
    (void)argc; (void)argv;
    printf("model %s | decisions %d | fps %d | free internal %u KB psram %u KB\n",
           s_model ? "loaded" : "NOT loaded", s_decisions, display_cat_fps(),
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
    return 0;
}

static int cmd_bright(int argc, char **argv) {
    if (argc > 1) display_cat_brightness(atoi(argv[1]));
    printf("brightness %d\n", argc > 1 ? atoi(argv[1]) : -1);
    return 0;
}

static void start_console(void) {
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t rc = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    rc.prompt = "cat> ";
    rc.max_cmdline_length = 320;
    esp_console_dev_usb_serial_jtag_config_t hw = ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    if (esp_console_new_repl_usb_serial_jtag(&hw, &rc, &repl) != ESP_OK) {
        ESP_LOGE(TAG, "no console"); return;
    }
    const esp_console_cmd_t cmds[] = {
        { .command = "food",     .help = "fill the food bowl",              .func = food },
        { .command = "water",    .help = "fill the water bowl",             .func = water },
        { .command = "play",     .help = "wave the toy",                    .func = play },
        { .command = "pet",      .help = "stroke the cat",                  .func = pet },
        { .command = "clean",    .help = "clean the litter box",            .func = clean },
        { .command = "status",   .help = "every drive + the current goal",  .func = cmd_status },
        { .command = "cat",      .help = "ask the brain a state line",      .func = cmd_cat },
        { .command = "bench",    .help = "bench [n] -> tokens/s",           .func = cmd_bench },
        { .command = "dotcheck", .help = "PIE vs scalar dot self-check",    .func = cmd_dotcheck },
        { .command = "info",     .help = "model, decisions, fps, memory",   .func = cmd_info },
        { .command = "help",     .help = "help: what everything does",        .func = cmd_help },
        { .command = "tap",      .help = "tap <raw_x> <raw_y> (inject a tap)", .func = cmd_tap },
        { .command = "flip",     .help = "flip: toggle a half turn (saved)",   .func = cmd_flip },
        { .command = "bright",   .help = "bright <0-100>",                  .func = cmd_bright },
    };
    for (size_t i = 0; i < sizeof cmds / sizeof cmds[0]; i++) esp_console_cmd_register(&cmds[i]);
    esp_console_start_repl(repl);
}

/* One tap, from any source: the touch chip, or the `tap` console command. The
 * mapping must exist in exactly one place so both paths agree. */
static const char *handle_tap(int rx, int ry) {
    int lx, ly;
    if (display_cat_flipped()) {
        lx = ry;                        /* vx = raw_y        */
        ly = 720 - 1 - rx;              /* vy = 719 - raw_x  */
    } else {
        lx = 1280 - 1 - ry;             /* vx = 1279 - raw_y */
        ly = rx;                        /* vy = raw_x        */
    }
    const char *hit = "nothing";
    display_cat_mark(lx, ly);
    float bd = 90.0f * 90.0f;
    if ((float)(lx - (int)(s_cat.x * 4)) * (lx - (int)(s_cat.x * 4)) +
        (float)(ly - (int)(s_cat.y * 4)) * (ly - (int)(s_cat.y * 4)) < bd) {
        cat_pet(&s_cat); hit = "pet";
    } else if (fabsf((float)lx - 216) < 90 && fabsf((float)ly - 512) < 90) { cat_feed(&s_cat); hit = "food"; }
    else if (fabsf((float)lx - 416) < 90 && fabsf((float)ly - 608) < 90) { cat_water(&s_cat); hit = "water"; }
    else if (fabsf((float)lx - 784) < 90 && fabsf((float)ly - 248) < 90) { cat_play_with(&s_cat); hit = "play"; }
    else if (fabsf((float)lx - 1144) < 90 && fabsf((float)ly - 584) < 90) { cat_clean_box(&s_cat); hit = "clean"; }
    else if (fabsf((float)lx - 1000) < 90 && fabsf((float)ly - 240) < 90) {
        s_cat.drives[CAT_BORED] = 9;
        snprintf(s_cat.notice, sizeof s_cat.notice, "scratching the tree");
        hit = "tree";
    }
    ESP_LOGI(TAG, "tap raw (%d,%d) -> screen (%d,%d) = %s | %s", rx, ry, lx, ly, hit, s_cat.notice);
    return hit;
}

static int cmd_tap(int argc, char **argv) {
    if (argc < 3) { printf("usage: tap <raw_x> <raw_y>\n"); return 1; }
    const char *hit = handle_tap(atoi(argv[1]), atoi(argv[2]));
    printf("tap -> %s | %s\n", hit, s_cat.notice);
    return 0;
}

/* ---- touch: tap the thing you mean ---- */
static void touch_task(void *arg) {
    esp_lcd_touch_handle_t tp = NULL;
    if (bsp_feature_enable(BSP_FEATURE_TOUCH, true) != ESP_OK)
        ESP_LOGW(TAG, "the touch chip's power (expander TOUCH_EN) did not switch");
    vTaskDelay(pdMS_TO_TICKS(500));           /* the BSP's own settle: it answers no sooner */
    if (bsp_touch_new(NULL, &tp) != ESP_OK || !tp) {
        ESP_LOGE(TAG, "no touch: the cat stays console-only");
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "touch ready: tap the bowl, the toy, the cat, the box");
    uint16_t raw_x[1], raw_y[1];
    while (1) {
        esp_lcd_touch_read_data(tp);
        uint8_t n = 0;
        if (esp_lcd_touch_get_coordinates(tp, raw_x, raw_y, NULL, &n, 1) && n > 0) {
            /* The chip reports in the glass's native portrait frame (the driver logs
             * Max.X 720, Max.Y 1280), i.e. in the same coordinates as the DSI buffer.
             * display_cat.c turns the view with  view(vx,vy) -> DSI(vy, 1279-vx),
             * so the inverse is  vx = 1279 - raw_y,  vy = raw_x. The previous
             * version used the pre-flip formula and mapped most taps off-screen. */
            int lx, ly;
            if (display_cat_flipped()) {          /* the touch must use the same turn */
                lx = (int)raw_y[0];               /* vx = raw_y        */
                ly = 720 - 1 - (int)raw_x[0];     /* vy = 719 - raw_x  */
            } else {
                lx = 1280 - 1 - (int)raw_y[0];    /* vx = 1279 - raw_y */
                ly = (int)raw_x[0];               /* vy = raw_x        */
            }
            const char *hit = "nothing";
            display_cat_mark(lx, ly);          /* so the hit point is visible under your finger */
            float bd = 90.0f * 90.0f;                 /* a finger is fat: 90 px radius */
            if ((float)(lx - (int)(s_cat.x * 4)) * (lx - (int)(s_cat.x * 4)) +
                (float)(ly - (int)(s_cat.y * 4)) * (ly - (int)(s_cat.y * 4)) < bd) {
                cat_pet(&s_cat); hit = "pet";
            } else if (fabsf((float)lx - 216) < 90 && fabsf((float)ly - 512) < 90) { cat_feed(&s_cat); hit = "food"; }
            else if (fabsf((float)lx - 416) < 90 && fabsf((float)ly - 608) < 90) { cat_water(&s_cat); hit = "water"; }
            else if (fabsf((float)lx - 784) < 90 && fabsf((float)ly - 248) < 90) { cat_play_with(&s_cat); hit = "play"; }
            else if (fabsf((float)lx - 1144) < 90 && fabsf((float)ly - 584) < 90) { cat_clean_box(&s_cat); hit = "clean"; }
            else if (fabsf((float)lx - 1000) < 90 && fabsf((float)ly - 240) < 90) {
                s_cat.drives[CAT_BORED] = 9; snprintf(s_cat.notice, sizeof s_cat.notice, "scratching the tree");
                hit = "tree";
            }
            ESP_LOGI(TAG, "tap raw (%d,%d) -> screen (%d,%d) = %s | %s",
                     (int)raw_x[0], (int)raw_y[0], lx, ly, hit, s_cat.notice);
            vTaskDelay(pdMS_TO_TICKS(400));           /* one action per tap */
        }
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}

/* ---- the clock, and the cat's memory of itself ----
 *
 * The state line carries `time dawn|day|dusk|night` and the model was trained with
 * it varying. Hard-coding "day" would mean the device only ever sees a quarter of
 * the training distribution, so the RTC is read for real. The RX8130CE at 0x32
 * holds BCD time in 0x10..0x16 (sec, min, hour, day, month, year).
 */
static i2c_master_dev_handle_t s_rtc;

static void rtc_init(void) {
    i2c_master_bus_handle_t bus = bsp_i2c_get_handle();
    if (!bus) { ESP_LOGW(TAG, "no i2c bus for the RTC"); return; }
    const i2c_device_config_t cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7,
                                      .device_address = 0x32, .scl_speed_hz = 100000 };
    if (i2c_master_bus_add_device(bus, &cfg, &s_rtc) != ESP_OK)
        ESP_LOGW(TAG, "the RTC at 0x32 did not answer");
}

static int rtc_hour(void) {
    if (!s_rtc) return -1;
    const uint8_t reg = 0x12;
    uint8_t v = 0;
    if (i2c_master_transmit_receive(s_rtc, &reg, 1, &v, 1, 100) != ESP_OK) return -1;
    int h = (v >> 4) * 10 + (v & 0x0F);
    return (h >= 0 && h < 24) ? h : -1;          /* not BCD -> the clock is not set */
}

static const char *rtc_tod(void) {
    int h = rtc_hour();
    if (h < 0) return NULL;
    if (h >= 5 && h < 10) return "dawn";
    if (h >= 10 && h < 17) return "day";
    if (h >= 17 && h < 21) return "dusk";
    return "night";
}

typedef struct {
    float drives[CAT_DRIVES];
    float x, y, heading, food, water;
    int goal_idx;
    uint8_t box;
} pet_save_t;

static void save_state(void) {
    nvs_handle_t h;
    if (nvs_open("pet", NVS_READWRITE, &h) != ESP_OK) return;
    pet_save_t s = { 0 };
    memcpy(s.drives, s_cat.drives, sizeof s.drives);
    s.x = s_cat.x; s.y = s_cat.y; s.heading = s_cat.heading;
    s.goal_idx = s_cat.goal_idx; s.food = s_cat.food_left; s.water = s_cat.water_left;
    s.box = s_cat.box_clean ? 1 : 0;
    if (nvs_set_blob(h, "state", &s, sizeof s) == ESP_OK) nvs_commit(h);
    nvs_close(h);
}

static void load_state(void) {
    nvs_handle_t h;
    pet_save_t s = { 0 };
    size_t len = sizeof s;
    if (nvs_open("pet", NVS_READONLY, &h) != ESP_OK) return;
    esp_err_t e = nvs_get_blob(h, "state", &s, &len);
    nvs_close(h);
    if (e != ESP_OK || len != sizeof s) return;
    for (int i = 0; i < CAT_DRIVES; i++)
        if (s.drives[i] >= 0 && s.drives[i] <= 9) s_cat.drives[i] = s.drives[i];
    if (s.x > 0 && s.x < 320 && s.y > 0 && s.y < 180) {
        s_cat.x = s.x; s_cat.y = s.y; s_cat.heading = s.heading;
    }
    if (s.goal_idx >= 0 && s.goal_idx < CAT_GOALS) cat_world_set_goal(&s_cat, cat_goal_names[s.goal_idx]);
    if (s.food >= 0 && s.food <= 3) s_cat.food_left = s.food;
    if (s.water >= 0 && s.water <= 3) s_cat.water_left = s.water;
    s_cat.box_clean = s.box != 0;
    ESP_LOGI(TAG, "cat remembered: hunger %d energy %d goal %s", (int)s_cat.drives[CAT_HUNGER],
             (int)s_cat.drives[CAT_ENERGY], s_cat.goal);
}

static int cmd_flip(int argc, char **argv) {
    bool on = display_cat_flipped();
    if (argc > 1) on = atoi(argv[1]) != 0;
    else on = !on;
    display_cat_flip(on);
    nvs_handle_t h;
    if (nvs_open("pet", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u8(h, "flip", on ? 1 : 0);
        nvs_commit(h);
        nvs_close(h);
    }
    printf("flip %s (saved; reboot keeps it)\n", on ? "on (half turn)" : "off");
    return 0;
}

static int cmd_help(int argc, char **argv) {
    (void)argc; (void)argv;
    printf("tap the screen:  food bowl = feed | water bowl = refill | toy = play |\n"
           "                 litter box = clean | tree = scratch | the cat = stroke\n"
           "console:\n"
           "  food water play pet clean   do it directly\n"
           "  status                      every drive + the current goal\n"
           "  cat <state line>            ask the brain\n"
           "  tap <raw_x> <raw_y>         inject a tap (self-check)\n"
           "  flip                        half turn (saved)\n"
           "  bench | dotcheck | info | bright <0-100>\n");
    return 0;
}

void app_main(void) {
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase(); nvs_flash_init();
    }
    nvs_handle_t fh;
    if (nvs_open("pet", NVS_READONLY, &fh) == ESP_OK) {
        uint8_t f = 0;
        if (nvs_get_u8(fh, "flip", &f) == ESP_OK) display_cat_flip(f != 0);
        nvs_close(fh);
    }
    cat_world_init(&s_cat);
    rtc_init();
    load_state();
    load_brain();
    if (display_cat_init()) {
        xTaskCreatePinnedToCore(render_task, "render", 8192, NULL, 4, NULL, 1);
        xTaskCreatePinnedToCore(touch_task, "touch", 6144, NULL, 3, NULL, 0);
        char line[256];
        cat_state_line(&s_cat, line, sizeof line);
        ESP_LOGI(TAG, "cat is on screen | state line: %s", line);
    } else {
        ESP_LOGE(TAG, "no display: the cat runs headless");
    }
    xTaskCreatePinnedToCore(brain_task, "brain", 12288, NULL, 3, NULL, 0);
    start_console();
}
