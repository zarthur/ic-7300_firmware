/* GFSK equations adapted from ft8_lib demo/gen_ft8.c (MIT, Karlis Goba).
 * Streaming synthesis replaces full-slot arrays; see THIRD_PARTY_NOTICES.md. */
#include "codec.h"
#include <ft8/encode.h>
#include <ft8/message.h>
#include <math.h>
#include <string.h>

/* Offline experiments may override these at build time; defaults are unchanged. */
#ifndef FT8_RX_CANDIDATES
#define FT8_RX_CANDIDATES 140
#endif
#ifndef FT8_RX_MIN_SCORE
#define FT8_RX_MIN_SCORE 10
#endif
#ifndef FT8_RX_ITERATIONS
#define FT8_RX_ITERATIONS 25
#endif
#ifndef FT8_RX_TIME_OSR
#define FT8_RX_TIME_OSR 2
#endif
#ifndef FT8_RX_FREQ_OSR
#define FT8_RX_FREQ_OSR 2
#endif
_Static_assert(FT8_RX_CANDIDATES > 0 && FT8_RX_CANDIDATES <= 1024, "bounded candidate workspace");
_Static_assert(FT8_RX_ITERATIONS > 0 && FT8_RX_ITERATIONS <= 200, "bounded iteration count");
_Static_assert(FT8_RX_MIN_SCORE >= 0 && FT8_RX_MIN_SCORE <= 255, "bounded sync threshold");
_Static_assert(FT8_RX_TIME_OSR == 2 || FT8_RX_TIME_OSR == 4, "supported time subdivision");
_Static_assert(FT8_RX_FREQ_OSR == 2 || FT8_RX_FREQ_OSR == 4, "supported frequency subdivision");

void ft8_rx_init(ft8_rx *rx,int64_t utc) {
    memset(rx,0,sizeof(*rx)); rx->slot_utc_ms=utc;
    monitor_config_t cfg={.f_min=200,.f_max=3000,.sample_rate=FT8_RATE,
        .time_osr=FT8_RX_TIME_OSR,.freq_osr=FT8_RX_FREQ_OSR,.protocol=FTX_PROTOCOL_FT8};
    monitor_init(&rx->monitor,&cfg);
}
bool ft8_rx_push(ft8_rx *rx,const float *samples,size_t count,int64_t first) {
    if(!rx || rx->samples>FT8_SLOT_SAMPLES || rx->pending>=1920 || (count && !samples)) return false;
    if(first!=(int64_t)rx->samples || count>FT8_SLOT_SAMPLES-rx->samples) return false;
    for(size_t i=0;i<count;i++) if(!isfinite(samples[i])) return false;
    while(count) {
        size_t room=1920-rx->pending;
        size_t take=count<room?count:room;
        memcpy(rx->frame+rx->pending,samples,take*sizeof(*samples));
        rx->pending+=take;rx->samples+=take;samples+=take;count-=take;
        if(rx->pending==1920) {monitor_process(&rx->monitor,rx->frame);rx->pending=0;}
    }
    return true;
}
int ft8_rx_finish(ft8_rx *rx,ft8_message_cb cb,void *user) {
    return ft8_rx_finish_observed(rx,cb,user,NULL,NULL);
}
int ft8_rx_finish_observed(ft8_rx *rx,ft8_message_cb cb,void *user,ft8_candidate_cb observe,void *observer_user) {
    ftx_candidate_t candidates[FT8_RX_CANDIDATES]; ftx_message_t seen[50];int count=0;
    int n=ftx_find_candidates(&rx->monitor.wf,FT8_RX_CANDIDATES,candidates,FT8_RX_MIN_SCORE);
    for(int i=0;i<n && count<50;i++) {
        const ftx_candidate_t *c=&candidates[i];
        ft8_candidate_result diagnostic={.rank=i,.total=n,.sync_score=c->score,.unpack_status=-1,
            .frequency_hz=(rx->monitor.min_bin+c->freq_offset+(float)c->freq_sub/rx->monitor.wf.freq_osr)/rx->monitor.symbol_period,
            .time_offset_s=(c->time_offset+(float)c->time_sub/rx->monitor.wf.time_osr)*rx->monitor.symbol_period};
        ftx_message_t message;ftx_decode_status_t status={0};
        if(!ftx_decode_candidate(&rx->monitor.wf,c,FT8_RX_ITERATIONS,&message,&status)) {
            diagnostic.ldpc_errors=status.ldpc_errors;
            diagnostic.stage=status.ldpc_errors ? "ldpc" : "crc";
            if(observe)observe(&diagnostic,observer_user);
            continue;
        }
        bool duplicate=false;
        for(int j=0;j<count;j++) if(!memcmp(seen[j].payload,message.payload,sizeof(message.payload))) duplicate=true;
        if(duplicate) {
            diagnostic.stage="duplicate";if(observe)observe(&diagnostic,observer_user);continue;
        }
        ft8_decoded result={0};ftx_message_offsets_t offsets;
        diagnostic.unpack_status=ftx_message_decode(&message,NULL,result.text,&offsets);
        if(diagnostic.unpack_status!=FTX_MESSAGE_RC_OK) {
            diagnostic.stage="unpack";if(observe)observe(&diagnostic,observer_user);continue;
        }
        seen[count++]=message;
        memcpy(result.payload,message.payload,sizeof(result.payload));
        ft8_encode(message.payload,result.tones);
        result.frequency_hz=diagnostic.frequency_hz;
        result.time_offset_s=diagnostic.time_offset_s;
        result.sync_score=c->score;result.slot_utc_ms=rx->slot_utc_ms;
        diagnostic.stage="decoded";if(observe)observe(&diagnostic,observer_user);
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
