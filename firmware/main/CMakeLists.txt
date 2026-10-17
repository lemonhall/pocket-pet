idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES llm esp_partition esp_timer console nvs_flash
    EMBED_FILES "cat_tok.bin"
)
