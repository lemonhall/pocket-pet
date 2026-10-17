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
            /* the reflex layer keeps the last word: do not send a thirsty cat to sleep */
            if (s_cat.drives[CAT_THIRST] < 6.0f) cat_world_set_goal(&s_cat, g);
        } else {
            ESP_LOGW(TAG, "the brain did not answer (%d ms)", ms);
        }
        ESP_LOGI(TAG, "cat: hunger %d energy %d bored %d litter %d thirst %d | goal %s | %d fps",
                 (int)s_cat.drives[CAT_HUNGER], (int)s_cat.drives[CAT_ENERGY],
                 (int)s_cat.drives[CAT_BORED], (int)s_cat.drives[CAT_LITTER],
                 (int)s_cat.drives[CAT_THIRST], s_cat.goal, display_cat_fps());
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
        { .command = "bright",   .help = "bright <0-100>",                  .func = cmd_bright },
    };
    for (size_t i = 0; i < sizeof cmds / sizeof cmds[0]; i++) esp_console_cmd_register(&cmds[i]);
    esp_console_start_repl(repl);
}

void app_main(void) {
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase(); nvs_flash_init();
    }
    cat_world_init(&s_cat);
    load_brain();
    if (display_cat_init()) {
        xTaskCreatePinnedToCore(render_task, "render", 8192, NULL, 4, NULL, 1);
        char line[256];
        cat_state_line(&s_cat, line, sizeof line);
        ESP_LOGI(TAG, "cat is on screen | state line: %s", line);
    } else {
        ESP_LOGE(TAG, "no display: the cat runs headless");
    }
    xTaskCreatePinnedToCore(brain_task, "brain", 12288, NULL, 3, NULL, 0);
    start_console();
}
