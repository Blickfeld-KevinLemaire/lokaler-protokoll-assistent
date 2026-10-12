#include "LVGL_Driver.h"
#include "esp_heap_caps.h"

static const char *TAG_LVGL = "LVGL";

lv_disp_draw_buf_t disp_buf;
lv_disp_drv_t disp_drv;
lv_indev_drv_t indev_drv;
lv_disp_t *disp;

static void example_increase_lvgl_tick(void *arg)
{
    lv_tick_inc(EXAMPLE_LVGL_TICK_PERIOD_MS);
}

static void example_lvgl_flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    esp_lcd_panel_handle_t panel = (esp_lcd_panel_handle_t) drv->user_data;
    esp_err_t ret = esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1, area->x2 + 1, area->y2 + 1, color_map);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG_LVGL, "Queue LCD DMA transfer failed: %s", esp_err_to_name(ret));
        /* LVGL nicht festhaengen lassen, wenn kein Transfer eingereiht werden konnte */
        lv_disp_flush_ready(drv);
    }
}

static bool example_lvgl_flush_ready_callback(esp_lcd_panel_io_handle_t panel_io,
                                              esp_lcd_panel_io_event_data_t *edata,
                                              void *user_ctx)
{
    (void)panel_io;
    (void)edata;
    lv_disp_flush_ready((lv_disp_drv_t *)user_ctx);
    return false;
}

static void example_touchpad_read(lv_indev_drv_t *drv, lv_indev_data_t *data)
{
    esp_lcd_touch_point_data_t point = {0};
    uint8_t touchpad_cnt = 0;

    esp_lcd_touch_read_data(drv->user_data);
    esp_err_t err = esp_lcd_touch_get_data(drv->user_data, &point, &touchpad_cnt, 1);

    if (err == ESP_OK && touchpad_cnt > 0) {
        data->point.x = point.x;
        data->point.y = point.y;
        data->state = LV_INDEV_STATE_PR;
    } else {
        data->state = LV_INDEV_STATE_REL;
    }
}

void LVGL_Init(void)
{
    ESP_LOGI(TAG_LVGL, "Initialize LVGL library");
    lv_init();

    lv_color_t *buf1 = heap_caps_malloc(LVGL_BUF_LEN * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    assert(buf1);
    lv_color_t *buf2 = heap_caps_malloc(LVGL_BUF_LEN * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    assert(buf2);
    lv_disp_draw_buf_init(&disp_buf, buf1, buf2, LVGL_BUF_LEN);

    ESP_LOGI(TAG_LVGL, "Register display driver to LVGL");
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = EXAMPLE_LCD_WIDTH;
    disp_drv.ver_res = EXAMPLE_LCD_HEIGHT;
    disp_drv.flush_cb = example_lvgl_flush_cb;
    disp_drv.draw_buf = &disp_buf;
    disp_drv.user_data = panel_handle;
    disp = lv_disp_drv_register(&disp_drv);

    const esp_lcd_panel_io_callbacks_t cbs = {
        .on_color_trans_done = example_lvgl_flush_ready_callback,
    };
    ESP_ERROR_CHECK(esp_lcd_panel_io_register_event_callbacks(panel_io_handle, &cbs, &disp_drv));

    Touch_Init();
    lv_indev_drv_init(&indev_drv);
    indev_drv.type = LV_INDEV_TYPE_POINTER;
    indev_drv.disp = disp;
    indev_drv.read_cb = example_touchpad_read;
    indev_drv.user_data = tp;
    lv_indev_drv_register(&indev_drv);

    ESP_LOGI(TAG_LVGL, "Install LVGL tick timer");
    const esp_timer_create_args_t lvgl_tick_timer_args = {
        .callback = &example_increase_lvgl_tick,
        .name = "lvgl_tick"
    };
    esp_timer_handle_t lvgl_tick_timer = NULL;
    ESP_ERROR_CHECK(esp_timer_create(&lvgl_tick_timer_args, &lvgl_tick_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(lvgl_tick_timer, EXAMPLE_LVGL_TICK_PERIOD_MS * 1000));
}
