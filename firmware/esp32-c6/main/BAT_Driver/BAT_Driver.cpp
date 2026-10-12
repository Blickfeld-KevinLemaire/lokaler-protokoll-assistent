#include "BAT_Driver.h"
#include "Audio_Board.h"

#include <cstring>
#include <cstdlib>
#include "esp_log.h"
#include "driver/i2c_master.h"

#define XPOWERS_CHIP_AXP2101
#include "XPowersLib.h"

#define PMU_I2C_TIMEOUT_MS  1000
#define PMU_I2C_SPEED_HZ    100000
#define BAT_OVERSAMPLE      8

static const char *TAG = "BAT";

static XPowersPMU PMU;
static i2c_master_dev_handle_t pmu_dev = NULL;
static bool pmu_ok = false;
static float last_volts = 0.0f;

static int pmu_register_read(uint8_t devAddr, uint8_t regAddr, uint8_t *data, uint8_t len)
{
    esp_err_t ret = i2c_master_transmit_receive(pmu_dev, &regAddr, 1, data, len, PMU_I2C_TIMEOUT_MS);
    return (ret == ESP_OK) ? 0 : -1;
}

static int pmu_register_write_byte(uint8_t devAddr, uint8_t regAddr, uint8_t *data, uint8_t len)
{
    uint8_t *buffer = (uint8_t *)malloc(len + 1);
    if (!buffer) return -1;
    buffer[0] = regAddr;
    memcpy(&buffer[1], data, len);
    esp_err_t ret = i2c_master_transmit(pmu_dev, buffer, len + 1, PMU_I2C_TIMEOUT_MS);
    free(buffer);
    return (ret == ESP_OK) ? 0 : -1;
}

void BAT_Init(void)
{
    i2c_device_config_t dev_config = {};
    dev_config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev_config.device_address = AXP2101_SLAVE_ADDRESS;
    dev_config.scl_speed_hz = PMU_I2C_SPEED_HZ;

    esp_err_t err = i2c_master_bus_add_device(esp_ret_i2c_handle(), &dev_config, &pmu_dev);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "AXP2101 am I2C-Bus nicht ansprechbar: %s", esp_err_to_name(err));
        return;
    }

    if (!PMU.begin(AXP2101_SLAVE_ADDRESS, pmu_register_read, pmu_register_write_byte)) {
        ESP_LOGE(TAG, "AXP2101 nicht gefunden");
        return;
    }

    /* Spannungsschienen bleiben unveraendert (Werkseinstellung des Boards). */
    PMU.enableVbusVoltageMeasure();
    PMU.enableBattVoltageMeasure();
    PMU.enableSystemVoltageMeasure();

    /* Ohne Akku-Temperaturfuehler muss die TS-Pin-Messung aus sein, sonst laedt der Chip nicht */
    PMU.disableTSPinMeasure();

    PMU.setPrechargeCurr(XPOWERS_AXP2101_PRECHARGE_50MA);
    PMU.setChargerConstantCurr(XPOWERS_AXP2101_CHG_CUR_400MA);
    PMU.setChargerTerminationCurr(XPOWERS_AXP2101_CHG_ITERM_25MA);
    PMU.setChargeTargetVoltage(XPOWERS_AXP2101_CHG_VOL_4V2);

    pmu_ok = true;
    ESP_LOGI(TAG, "AXP2101 bereit: Akku %s, %u mV, USB %s",
             PMU.isBatteryConnect() ? "angeschlossen" : "nicht angeschlossen",
             (unsigned)PMU.getBattVoltage(),
             PMU.isVbusIn() ? "ja" : "nein");
}

float BAT_Get_Volts(void)
{
    if (!pmu_ok || !PMU.isBatteryConnect()) {
        return 0.0f;
    }

    /* Mehrfach lesen und mitteln, wie beim S3 (dort ADC-Oversampling) */
    uint32_t sum = 0;
    int valid = 0;
    for (int i = 0; i < BAT_OVERSAMPLE; i++) {
        uint16_t mv = PMU.getBattVoltage();
        if (mv > 0) {
            sum += mv;
            valid++;
        }
    }
    if (valid > 0) {
        last_volts = (float)sum / (float)valid / 1000.0f;
    }
    return last_volts;
}

bool BAT_Vbus_Present(void)
{
    return pmu_ok && PMU.isVbusIn();
}

bool BAT_Is_Charging(void)
{
    return pmu_ok && PMU.isCharging();
}
