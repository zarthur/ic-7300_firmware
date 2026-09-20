#ifndef IC7300_CODEC_H
#define IC7300_CODEC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <common/monitor.h>
#define FT8_RATE 12000
#define FT8_SLOT_SAMPLES 180000
#define FT8_SIGNAL_SAMPLES 151680
typedef struct {
    char text[40]; float frequency_hz, time_offset_s; int sync_score;
    int64_t slot_utc_ms;
} ft8_decoded;
typedef void (*ft8_message_cb)(const ft8_decoded *,void *);
typedef struct {
    monitor_t monitor;
    float frame[1920]; size_t pending, samples;
    int64_t slot_utc_ms;
} ft8_rx;
typedef struct {
    uint8_t tones[79]; float pulse[5760];
    double phase; float hz; size_t sample;
    bool cancelled;
} ft8_tx;
/* Mono float PCM, 12 kHz. Caller supplies one aligned UTC slot at a time. */
void ft8_rx_init(ft8_rx *,int64_t slot_utc_ms);
bool ft8_rx_push(ft8_rx *,const float *,size_t count,int64_t first_sample_index);
int ft8_rx_finish(ft8_rx *,ft8_message_cb,void *);
void ft8_rx_free(ft8_rx *);
bool ft8_tx_init(ft8_tx *,const char *message,float base_hz);
size_t ft8_tx_pull(ft8_tx *,float *output,size_t capacity);
void ft8_tx_cancel(ft8_tx *);
#endif
