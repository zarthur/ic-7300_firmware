#include "codec.h"
#include "alloc.h"
#include "station.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static int messages;
static void decoded(const ft8_decoded *m,void *user){(void)user;if(!strcmp(m->text,"CQ K1ABC FN42"))messages++;}
int main(void){
    ft8_tx tx;ft8_rx rx;float buffer[960];
    assert(ft8_tx_init(&tx,"CQ K1ABC FN42",1000));
    assert(tx.tones[0]==3&&tx.tones[1]==1&&tx.tones[2]==4&&tx.tones[78]==2);
    ft8_rx_init(&rx,0);memset(buffer,0,sizeof(buffer));
    for(int i=0;i<6;i++)assert(ft8_rx_push(&rx,buffer,960,rx.samples));
    assert(ft8_rx_push(&rx,buffer,240,rx.samples));
    size_t n,total=0;while((n=ft8_tx_pull(&tx,buffer,960))){assert(ft8_rx_push(&rx,buffer,n,rx.samples));total+=n;}
    assert(total==151680);memset(buffer,0,sizeof(buffer));
    while(rx.samples<180000){n=180000-rx.samples;if(n>960)n=960;assert(ft8_rx_push(&rx,buffer,n,rx.samples));}
    assert(!ft8_rx_push(&rx,buffer,1,rx.samples));assert(ft8_rx_finish(&rx,decoded,NULL)>=1);assert(messages==1);
    ft8_rx_free(&rx);assert(tracked_live()==0);
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
    puts("codec tests passed: streaming loopback, symbol sync, sample continuity, bounds, cancellation");
}
