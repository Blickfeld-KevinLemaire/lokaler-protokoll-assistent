cmake_minimum_required(VERSION 3.16)

# Gemeinsame Komponenten aller Geraete (u. a. vermerk_upload: Upload an die Protokoll-Software)
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(VERMERK-S3-AUDIO)
