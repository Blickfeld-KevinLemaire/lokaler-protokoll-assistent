idf_component_register(
    SRCS "e2e_main.c"
    PRIV_REQUIRES
        vermerk_upload
        protocol_examples_common
        esp_netif
        esp_event
        nvs_flash
        fatfs
        wear_levelling
)
