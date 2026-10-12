# Ende-zu-Ende-Test der Upload-Komponente in QEMU (ESP32) gegen den echten Empfang der Protokoll-Software.
# Start: run_e2e.sh (baut, startet Empfang, Proxy und QEMU, prueft das Ergebnis).
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/../../.."                                  # firmware/components
    "$ENV{IDF_PATH}/examples/common_components/protocol_examples_common"  # Ethernet in QEMU
)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(vermerk-upload-e2e)
