idf_component_register(
    SRCS "main.c" "cat_world.c" "display_cat.c"
    INCLUDE_DIRS "."
    REQUIRES llm esp_partition esp_timer console nvs_flash
             espressif__m5stack_tab5_noglib esp_lcd esp_driver_i2c
    EMBED_FILES "cat_tok.bin" "room.bin" "sprites.bin" "labels.bin" "legend.bin"
)

# IDF does not hand esp_driver_ppa's include down through REQUIRES (same trap
# pocket-tank hit); add it by hand.
target_include_directories(${COMPONENT_LIB} PRIVATE "${IDF_PATH}/components/esp_driver_ppa/include")
target_link_libraries(${COMPONENT_LIB} PRIVATE idf::esp_driver_ppa)

