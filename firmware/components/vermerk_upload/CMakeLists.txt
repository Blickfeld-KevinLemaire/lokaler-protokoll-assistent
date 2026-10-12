# Gemeinsame Upload-Komponente aller drei Geraete (GERAETE-SCHNITTSTELLE.md, Version 1).
#   vermerk_protokoll.c        reiner C-Teil ohne ESP-IDF, auf dem PC getestet (test/host/)
#   vermerk_upload.c           HTTP, SHA-256, Lesen der Datei
#   vermerk_konfig.c           Einstellungen (heute fest beim Bauen eingetragen)
#   vermerk_konfig_gemeinsam.c Auswahl je Ziel, Geraete-Id
#   vermerk_konfig_test.c      nur im QEMU-Test (CONFIG_VERMERK_KONFIG_TEST) statt vermerk_konfig.c
#
# vermerk_konfig.c liest server_config.h, wifi_credentials.h und vermerk_board.h aus dem Projekt des
# Boards (main/Wireless/). Nur diese eine Datei sieht den Ordner.

if(CONFIG_VERMERK_KONFIG_TEST)
    set(vermerk_konfig_quelle "vermerk_konfig_test.c")
else()
    set(vermerk_konfig_quelle "vermerk_konfig.c")
endif()

idf_component_register(
    SRCS
        "vermerk_protokoll.c"
        "vermerk_upload.c"
        "vermerk_konfig_gemeinsam.c"
        "${vermerk_konfig_quelle}"
    INCLUDE_DIRS
        "include"
    PRIV_REQUIRES
        esp_http_client
        esp_timer
        esp_hw_support
        mbedtls
)

# Beim ersten Durchlauf (nur Abhaengigkeiten ermitteln) gibt es noch kein Build-Ziel.
if(NOT CMAKE_BUILD_EARLY_EXPANSION AND NOT CONFIG_VERMERK_KONFIG_TEST)
    idf_build_get_property(vermerk_projekt PROJECT_DIR)
    set(vermerk_konfig_dir "${vermerk_projekt}/main/Wireless")
    foreach(vermerk_datei server_config.h wifi_credentials.h vermerk_board.h)
        if(NOT EXISTS "${vermerk_konfig_dir}/${vermerk_datei}")
            message(FATAL_ERROR
                "${vermerk_konfig_dir}/${vermerk_datei} fehlt. Bei server_config.h und wifi_credentials.h "
                "die Vorlage *.example daneben kopieren und ausfuellen (siehe firmware/README.md).")
        endif()
    endforeach()
    set_source_files_properties(vermerk_konfig.c PROPERTIES INCLUDE_DIRECTORIES "${vermerk_konfig_dir}")
endif()
