/* main.c - the smallest thing that proves the cat's brain runs on the Tab5.
 *
 * REQ-0001-008 asked for "the 14M student on the device, engine and SIMD kernels
 * unchanged". This firmware is that claim, made checkable:
 *   - the weights are build/cat_q4.bin (7.57 MB, pocket-tank's "ak42" v3 format),
 *     flashed into the `model` partition at 0x290000 (the same offset the tank
 *     uses, so the two models can be swapped with a single esptool write);
 *   - the tokenizer is build/cat_tok.bin, embedded, read by word_tok.c verbatim;
 *   - the engine is pocket-tank's q4_model.c + word_tok.c, copied into
 *     firmware/vendor/llm with no edits (that is the point);
 *   - inference is restricted to the eight goal tokens via q4_model_decide(),
 *     exactly as the tank restricts its own decision to its goal set.
 *
 * Console:
 *   cat hunger 6 energy 3 ... time night   -> prints the goal it picks
 *   bench                                   -> tokens/s (REQ-0001-008's >=8 gate)
 *   dotcheck                                -> PIE vs scalar dot self-check
 *   info                                    -> what was loaded
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>

#include "esp_log.h"
#include "esp_partition.h"
#include "esp_heap_caps.h"
#include "esp_console.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "q4_model.h"
#include "word_tok.h"

static const char *TAG = "catbrain";

extern const uint8_t cat_tok_bin_start[] asm("_binary_cat_tok_bin_start");
extern const uint8_t cat_tok_bin_end[]   asm("_binary_cat_tok_bin_end");

#define CAT_VOCAB 53
static const char *GOALS[8] = { "seek_food", "sleep", "play", "groom",
                                "follow_owner", "scratch", "explore", "hide" };

static q4_model_t *s_model;
static word_tok_t  s_tok;
static int         s_goal_id[8];
static uint32_t    s_rng = 0x1234567u;

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
    esp_err_t err = esp_partition_mmap(mp, 0, mp->size, ESP_PARTITION_MMAP_DATA, &map, &h);
    if (err != ESP_OK) { ESP_LOGE(TAG, "mmap failed: %s", esp_err_to_name(err)); return; }

    q4_fast_alloc = psram_alloc;
    q4_clock_us = esp_timer_get_time;
    s_model = q4_model_open((const uint8_t *)map, mp->size, psram_alloc);
    if (!s_model) {
        uint32_t magic = 0; memcpy(&magic, map, 4);
        ESP_LOGE(TAG, "q4_model_open failed (first 4 bytes 0x%08x, want 0x616b3432 = \"ak42\")", (unsigned)magic);
        return;
    }
    const q4_config_t *c = q4_model_config(s_model);
    size_t tok_len = (size_t)(cat_tok_bin_end - cat_tok_bin_start);
    if (word_tok_init(&s_tok, cat_tok_bin_start, tok_len, CAT_VOCAB) != 0) {
        ESP_LOGE(TAG, "tokenizer init failed"); s_model = NULL; return;
    }
    for (int i = 0; i < 8; i++) {
        s_goal_id[i] = goal_id_of(GOALS[i]);
        if (s_goal_id[i] < 0) ESP_LOGW(TAG, "goal %s not in the vocabulary", GOALS[i]);
    }
    ESP_LOGI(TAG, "brain ready: dim %d hidden %d layers %d heads %d vocab %d seq %d | tokenizer %u bytes",
             c->dim, c->hidden_dim, c->n_layers, c->n_heads, c->vocab_size, c->seq_len, (unsigned)tok_len);
    ESP_LOGI(TAG, "goal ids: seek_food %d sleep %d play %d groom %d follow_owner %d scratch %d explore %d hide %d",
             s_goal_id[0], s_goal_id[1], s_goal_id[2], s_goal_id[3],
             s_goal_id[4], s_goal_id[5], s_goal_id[6], s_goal_id[7]);
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
    if (n < 2) { printf("nothing to encode\n"); return 1; }
    if (toks[0] != 1) { printf("warning: BOS is %d, expected 1\n", toks[0]); }

    float probs[8]; int out[2];
    int64_t t0 = esp_timer_get_time();
    int nout = q4_model_decide(s_model, toks, n, s_goal_id, 8, 0.0f, &s_rng, probs, out, 1);
    int64_t us = esp_timer_get_time() - t0;
    if (nout < 1) { printf("no answer\n"); return 1; }

    const char *pick = "?";
    for (int i = 0; i < 8; i++) if (s_goal_id[i] == out[0]) pick = GOALS[i];
    printf("cat: %s\n  -> %s   (%lld ms, %d prompt tokens)\n", line, pick, (long long)(us / 1000), n);
    printf("  p:");
    for (int i = 0; i < 8; i++) printf(" %s %.2f", GOALS[i], probs[i]);
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
    int r = q4_model_dot_check();
    printf("dotcheck: %s (%d)\n", r == -1 ? "the PIE dot matches the scalar dot" : "MISMATCH", r);
    return r == -1 ? 0 : 1;
}

static int cmd_info(int argc, char **argv) {
    printf("model: %s\n", s_model ? "loaded" : "NOT loaded");
    if (s_model) {
        const q4_config_t *c = q4_model_config(s_model);
        printf("  dim %d hidden %d layers %d heads %d kv %d vocab %d seq %d\n",
               c->dim, c->hidden_dim, c->n_layers, c->n_heads, c->n_kv_heads, c->vocab_size, c->seq_len);
    }
    printf("  free internal %u KB, psram %u KB\n",
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024),
           (unsigned)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
    return 0;
}

static void start_console(void) {
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t rc = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    rc.prompt = "cat> ";
    rc.max_cmdline_length = 256;
    esp_console_dev_usb_serial_jtag_config_t hw = ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    if (esp_console_new_repl_usb_serial_jtag(&hw, &rc, &repl) != ESP_OK) {
        ESP_LOGE(TAG, "no console"); return;
    }
    const esp_console_cmd_t cmds[] = {
        { .command = "cat",      .help = "cat <state line> -> the goal it picks", .func = cmd_cat },
        { .command = "bench",    .help = "bench [n] -> tokens/s",                 .func = cmd_bench },
        { .command = "dotcheck", .help = "PIE vs scalar dot self-check",          .func = cmd_dotcheck },
        { .command = "info",     .help = "what is loaded",                        .func = cmd_info },
    };
    for (size_t i = 0; i < sizeof cmds / sizeof cmds[0]; i++) esp_console_cmd_register(&cmds[i]);
    esp_console_start_repl(repl);
}

void app_main(void) {
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase(); nvs_flash_init();
    }
    load_brain();
    start_console();
}
