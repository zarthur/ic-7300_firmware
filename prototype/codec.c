/* GFSK equations adapted from ft8_lib demo/gen_ft8.c (MIT, Karlis Goba).
 * Streaming synthesis replaces full-slot arrays; see THIRD_PARTY_NOTICES.md. */
#include "codec.h"
#include <ft8/encode.h>
#include <ft8/message.h>
#include <math.h>
#include <string.h>

void ft8_rx_init(ft8_rx *rx,int64_t utc) {
    memset(rx,0,sizeof(*rx)); rx->slot_utc_ms=utc;
    monitor_config_t cfg={.f_min=200,.f_max=3000,.sample_rate=FT8_RATE,
        .time_osr=2,.freq_osr=2,.protocol=FTX_PROTOCOL_FT8};
    monitor_init(&rx->monitor,&cfg);
}
bool ft8_rx_push(ft8_rx *rx,const float *samples,size_t count,int64_t first) {
    if(first!=(int64_t)rx->samples || count>FT8_SLOT_SAMPLES-rx->samples) return false;
    for(size_t i=0;i<count;i++) if(!isfinite(samples[i])) return false;
    for(size_t i=0;i<count;i++) {
        rx->frame[rx->pending++]=samples[i]; rx->samples++;
        if(rx->pending==1920) {monitor_process(&rx->monitor,rx->frame);rx->pending=0;}
    }
    return true;
}
int ft8_rx_finish(ft8_rx *rx,ft8_message_cb cb,void *user) {
    ftx_candidate_t candidates[140]; ftx_message_t seen[50];int count=0;
    int n=ftx_find_candidates(&rx->monitor.wf,140,candidates,10);
    for(int i=0;i<n && count<50;i++) {
        ftx_message_t message;ftx_decode_status_t status;
        if(!ftx_decode_candidate(&rx->monitor.wf,&candidates[i],25,&message,&status)) continue;
        bool duplicate=false;
        for(int j=0;j<count;j++) if(!memcmp(seen[j].payload,message.payload,sizeof(message.payload))) duplicate=true;
        if(duplicate) continue;
        ft8_decoded result={0};ftx_message_offsets_t offsets;
        if(ftx_message_decode(&message,NULL,result.text,&offsets)!=FTX_MESSAGE_RC_OK) continue;
        seen[count++]=message;
        const ftx_candidate_t *c=&candidates[i];
        result.frequency_hz=(rx->monitor.min_bin+c->freq_offset+(float)c->freq_sub/2)/rx->monitor.symbol_period;
        result.time_offset_s=(c->time_offset+(float)c->time_sub/2)*rx->monitor.symbol_period;
        result.sync_score=c->score;result.slot_utc_ms=rx->slot_utc_ms;
        cb(&result,user);
    }
    return count;
}
void ft8_rx_free(ft8_rx *rx) {monitor_free(&rx->monitor);}
bool ft8_tx_init(ft8_tx *tx,const char *text,float hz) {
    ftx_message_t message;
    if(!isfinite(hz)||hz<200||hz>2900||!text||strlen(text)>=40
        ||ftx_message_encode(&message,NULL,text)!=FTX_MESSAGE_RC_OK) return false;
    memset(tx,0,sizeof(*tx));tx->hz=hz;ft8_encode(message.payload,tx->tones);
    for(int j=0;j<5760;j++) {
        float t=j/1920.0f-1.5f;
        tx->pulse[j]=(erff(5.336446f*2*(t+0.5f))-erff(5.336446f*2*(t-0.5f)))/2;
    }
    return true;
}
size_t ft8_tx_pull(ft8_tx *tx,float *out,size_t capacity) {
    if(tx->cancelled) return 0;
    size_t n=FT8_SIGNAL_SAMPLES-tx->sample;if(n>capacity)n=capacity;
    for(size_t k=0;k<n;k++,tx->sample++) {
        int sample=(int)tx->sample, center=sample+1920;
        double weighted=0;
        for(int tone=center/1920-2;tone<=center/1920;tone++) {
            int p=center-tone*1920;
            if(p<0||p>=5760)continue;
            int index=tone<0?0:(tone>78?78:tone);
            weighted+=tx->tones[index]*tx->pulse[p];
        }
        float value=(float)sin(tx->phase);
        int ramp=sample<240?sample:(FT8_SIGNAL_SAMPLES-1-sample<240?FT8_SIGNAL_SAMPLES-1-sample:240);
        if(ramp<240)value*=(float)((1-cos(M_PI*ramp/240))/2);
        out[k]=value;
        tx->phase=fmod(tx->phase+2*M_PI*(tx->hz/FT8_RATE+weighted/1920),2*M_PI);
    }
    return n;
}
void ft8_tx_cancel(ft8_tx *tx) {tx->cancelled=true;}
