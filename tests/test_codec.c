#include "codec.h"
#include "alloc.h"
#include "station.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    int total;
    int expected;
} decode_result;

static float waveform[FT8_SIGNAL_SAMPLES];

static void decoded(const ft8_decoded *m,void *user){
    decode_result *result=user;
    result->total++;
    if(!strcmp(m->text,"CQ K1ABC FN42"))result->expected++;
}

static void feed_zeros(ft8_rx *rx,float *buffer,size_t target){
    memset(buffer,0,1921*sizeof(*buffer));
    while(rx->samples<target){
        size_t n=target-rx->samples;
        if(n>960)n=960;
        assert(ft8_rx_push(rx,buffer,n,rx->samples));
    }
}

int main(void){
    ft8_tx tx;ft8_rx rx;float buffer[1921];
    assert(ft8_tx_init(&tx,"CQ K1ABC FN42",1000));
    assert(tx.tones[0]==3&&tx.tones[1]==1&&tx.tones[2]==4&&tx.tones[78]==2);

    ft8_rx_init(&rx,0);memset(buffer,0,sizeof(buffer));
    assert(!ft8_rx_push(NULL,buffer,1,0));
    assert(!ft8_rx_push(&rx,NULL,1,0));
    assert(ft8_rx_push(&rx,NULL,0,0));
    assert(!ft8_rx_push(&rx,buffer,FT8_SLOT_SAMPLES+1,0));
    assert(rx.samples==0&&rx.pending==0);
    ft8_rx_free(&rx);

    /* A late invalid sample rejects the entire multi-frame call before it
       consumes the valid prefix or disturbs a frame already in progress. */
    ft8_rx_init(&rx,0);
    float prefix[1919]={0};prefix[0]=0.25f;
    assert(ft8_rx_push(&rx,prefix,1919,0));
    assert(rx.samples==1919&&rx.pending==1919&&rx.frame[0]==0.25f);
    float invalid_large[4001]={0};invalid_large[0]=0.5f;invalid_large[4000]=NAN;
    assert(!ft8_rx_push(&rx,invalid_large,4001,1919));
    assert(rx.samples==1919&&rx.pending==1919&&rx.frame[0]==0.25f);
    invalid_large[4000]=0.75f;
    assert(ft8_rx_push(&rx,invalid_large,4001,1919));
    assert(rx.samples==5920&&rx.pending==160&&rx.frame[159]==0.75f);
    ft8_rx_free(&rx);

    /* Build the exact same FT8 signal, then compare one large ingress call
       against irregular smaller blocks. The signal itself is 79 full frames. */
    const size_t chunks[]={17,1919,1921,1,960,193,1440};
    size_t n,total=0,chunk=0;
    while((n=ft8_tx_pull(&tx,waveform+total,chunks[chunk++%(sizeof(chunks)/sizeof(chunks[0]))])))total+=n;
    assert(total==FT8_SIGNAL_SAMPLES);

    ft8_rx whole,split;
    ft8_rx_init(&whole,0);ft8_rx_init(&split,0);
    feed_zeros(&whole,buffer,6000);
    feed_zeros(&split,buffer,6000);
    assert(whole.pending==240&&split.pending==240);

    assert(ft8_rx_push(&whole,waveform,FT8_SIGNAL_SAMPLES,whole.samples));
    assert(whole.samples==6000+FT8_SIGNAL_SAMPLES&&whole.pending==240);
    total=0;chunk=0;
    while(total<FT8_SIGNAL_SAMPLES){
        n=chunks[chunk++%(sizeof(chunks)/sizeof(chunks[0]))];
        if(n>FT8_SIGNAL_SAMPLES-total)n=FT8_SIGNAL_SAMPLES-total;
        assert(ft8_rx_push(&split,waveform+total,n,split.samples));
        total+=n;
    }
    assert(split.samples==whole.samples&&split.pending==whole.pending);

    feed_zeros(&whole,buffer,180000);
    feed_zeros(&split,buffer,180000);
    assert(!ft8_rx_push(&whole,buffer,1,whole.samples));
    decode_result whole_result={0},split_result={0};
    assert(ft8_rx_finish(&whole,decoded,&whole_result)>=1);
    assert(ft8_rx_finish(&split,decoded,&split_result)>=1);
    assert(whole_result.total==1&&whole_result.expected==1);
    assert(split_result.total==1&&split_result.expected==1);
    assert(whole_result.total==split_result.total&&whole_result.expected==split_result.expected);
    ft8_rx_free(&whole);ft8_rx_free(&split);assert(tracked_live()==0);

    assert(ft8_tx_init(&tx,"CQ K1ABC FN42",1000));assert(ft8_tx_pull(&tx,buffer,10)==10);
    ft8_tx_cancel(&tx);assert(ft8_tx_pull(&tx,buffer,960)==0);
    assert(!ft8_tx_init(&tx,"CQ K1ABC FN42",NAN));assert(!ft8_tx_init(&tx,"CQ K1ABC FN42",0));
    ft8_rx_init(&rx,0);assert(!ft8_rx_push(&rx,buffer,10,1));buffer[0]=NAN;assert(!ft8_rx_push(&rx,buffer,1,0));ft8_rx_free(&rx);

    ft8_station station={0};assert(qso_init(&station.qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    assert(qso_set_time_policy(&station.qso,1000,20));qso_enable(&station.qso);
    qso_clock_sample clock={500,500,500,0,true};
    assert(station_tick(&station,&clock,1000));
    assert(station_audio(&station,&clock,buffer,960)==960);station_cancel(&station);
    assert(station_audio(&station,&clock,buffer,960)==0);
    /* The host backend must acknowledge cancellation before reuse. */
    assert(station_backend_report(&station,&station.reservation,
                                 STATION_BACKEND_ABORTED,0,&clock));
    assert(qso_init(&station.qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    assert(qso_set_time_policy(&station.qso,1000,20));qso_enable(&station.qso);
    assert(station_tick(&station,&clock,1000));
    qso_clock_sample jumped={2000,1000,1000,0,true};
    assert(!station_tick(&station,&jumped,1000));
    assert(station_audio(&station,&jumped,buffer,960)==0);
    puts("codec tests passed: multi-frame ingress, chunked decode equivalence, atomic rejection, cancellation");
}
