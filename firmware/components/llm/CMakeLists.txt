# The inference engine is pocket-tank's, copied verbatim into firmware/vendor/llm
# (q4_model.c + word_tok.c). The cat's only contribution is the weights and the
# vocabulary, which is the whole point of REQ-0001-008: no engine changes.
set(LLM ${CMAKE_CURRENT_LIST_DIR}/../../vendor/llm)
idf_component_register(
    SRCS "${LLM}/q4_model.c" "${LLM}/word_tok.c"
    INCLUDE_DIRS "${LLM}"
    REQUIRES esp_timer
)
target_compile_options(${COMPONENT_LIB} PRIVATE -O3 -ffast-math)
