idf_component_register(
                         SRCS 
                              "./main.c" 
                              "./EXIO/TCA9554PWR.c"
                              "./MIC_Driver/MIC_Speech.c" 
                              "./LCD_Driver/esp_lcd_st77916/esp_lcd_st77916.c" 
                              "./LCD_Driver/ST77916.c"
                              "./Touch_Driver/esp_lcd_touch/esp_lcd_touch.c"        
                              "./Touch_Driver/CST816.c"  
                              "./LVGL_Driver/LVGL_Driver.c"
                              # LVGL_UI/LVGL_Example.c und LVGL_Music.c (Demo-Oberflaechen) sind nicht mehr Teil des Builds:
                              # sie brauchen die LVGL-Demos und damit einen groesseren LVGL-Speicherpool im knappen internen RAM.
                              "./SD_Card/SD_MMC.c" 
                              "./PCF85063/PCF85063.c"
                              "./BAT_Driver/BAT_Driver.c"
                              "./Wireless/Wireless.c"
                              "./Audio_Driver/Audio_Driver.c" 
                              "./Opus_Encoder/Opus_Encoder.c"
                              "./Gain_Control/Gain_Control.c"

                         INCLUDE_DIRS 
                              "./Audio_Driver" 
                              "./Opus_Encoder"
                              "./Gain_Control"
                              "./MIC_Driver" 
                              "./LCD_Driver/esp_lcd_st77916" 
                              "./LCD_Driver" 
                              "./Touch_Driver/esp_lcd_touch"     
                              "./Touch_Driver"
                              "./LVGL_Driver" 
                              "./LVGL_UI" 
                              "./EXIO"
                              "./SD_Card" 
                              "./PCF85063"
                              "./BAT_Driver"
                              "./Wireless"
                              "."
                       )
