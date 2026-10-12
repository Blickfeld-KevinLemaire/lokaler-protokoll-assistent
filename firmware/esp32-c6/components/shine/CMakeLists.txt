# shine: Festkomma-MP3-Encoder (LGPL-2.0), https://github.com/toots/shine
# VERMERK-Anpassungen gegenueber dem Original:
#  - feste Rechentabellen als const-Daten im Flash (shine_tables.c) statt im RAM
#  - MAX_CHANNELS=1: wir kodieren nur Mono (halbiert die Kanal-Puffer)
#  - shine_restart(): Encoder ohne Neu-Allokation zuruecksetzen
idf_component_register(
    SRC_DIRS "src"
    INCLUDE_DIRS "src"
)
target_compile_definitions(${COMPONENT_LIB} PRIVATE MAX_CHANNELS=1)
component_compile_options(-w)
