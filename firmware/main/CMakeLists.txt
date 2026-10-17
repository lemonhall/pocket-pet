idf_component_register(
    SRCS "main.c" "cat_world.c" "display_cat.c"
    INCLUDE_DIRS "."
    REQUIRES llm esp_partition esp_timer console nvs_flash
             espressif__m5stack_tab5_noglib esp_lcd esp_driver_i2c
    EMBED_FILES "cat_tok.bin" "room.bin" "sprites.bin" "labels.bin"
)
