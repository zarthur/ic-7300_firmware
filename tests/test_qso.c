#include "qso.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static qso_clock_sample sample_at(int64_t utc,int64_t mono,int64_t sync,
                                  int64_t uncertainty,bool valid) {
    qso_clock_sample sample={utc,mono,sync,uncertainty,valid};return sample;
}
static qso_t newq(int parity,int retries) {
    qso_t q;assert(qso_init(&q,"K1ABC","FN42","W9XYZ",-10,parity,retries));
    assert(qso_set_time_policy(&q,1000,20));return q;
}
static bool tick_sample(qso_t *q,int64_t utc,int64_t mono,int64_t sync,
                        int64_t uncertainty,bool valid,qso_tx *tx) {
    qso_clock_sample sample=sample_at(utc,mono,sync,uncertainty,valid);
    return qso_tick(q,&sample,tx);
}
static bool tick(qso_t *q,int64_t utc,int64_t mono,qso_tx *tx) {
    return tick_sample(q,utc,mono,mono,0,true,tx);
}
static qso_tx send(qso_t *q,int64_t t) {
    qso_tx tx;qso_clock_sample sample=sample_at(t,t,t,0,true);
    assert(qso_tick(q,&sample,&tx));assert(qso_tx_valid_at(q,&tx,&sample));
    qso_tx_finished(q,&tx,&sample,true);return tx;
}
static void test_repeated_sample_does_not_repeat_reservation(void) {
    qso_t q=newq(0,2);qso_tx tx;
    qso_clock_sample same=sample_at(500,500,500,0,true);
    qso_enable(&q);
    assert(qso_tick(&q,&same,&tx));
    uint32_t generation=q.generation;
    assert(!qso_tick(&q,&same,&tx));
    assert(q.active && q.state==QSO_GRID && q.generation==generation);
    assert(qso_tx_valid_at(&q,&tx,&same));
    qso_tx_finished(&q,&tx,&same,true);
    assert(!q.active && q.enabled && q.state==QSO_GRID);
    assert(!qso_tick(&q,&same,&tx));
    assert(!q.active && q.state==QSO_GRID && q.generation==generation);
}
int main(void) {
    qso_t q=newq(0,2); qso_tx tx;
    assert(!tick(&q,500,500,&tx));qso_enable(&q);
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",1));
    tx=send(&q,500);assert(!strcmp(tx.text,"W9XYZ K1ABC FN42"));
    assert(!tick(&q,501,501,&tx));
    assert(!qso_receive(&q,"K1ABC W1ZZZ -12",1));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",3));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12 extra",1));
    assert(qso_receive(&q,"K1ABC W9XYZ -12",1));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",1));
    tx=send(&q,30500);assert(!strcmp(tx.text,"W9XYZ K1ABC R-10"));
    assert(qso_receive(&q,"K1ABC W9XYZ RR73",3));
    tx=send(&q,60500);assert(!strcmp(tx.text,"W9XYZ K1ABC 73"));assert(q.state==QSO_COMPLETE);
    assert(!tick(&q,90500,90500,&tx));
    q=newq(1,1);qso_enable(&q);send(&q,15500);
    assert(qso_receive(&q,"K1ABC W9XYZ EN50",2));send(&q,45500);
    assert(qso_receive(&q,"K1ABC W9XYZ R-08",4));send(&q,75500);assert(q.state==QSO_COMPLETE);
    q=newq(0,1);qso_enable(&q);send(&q,500);send(&q,30500);
    assert(!tick(&q,60500,60500,&tx));assert(q.state==QSO_EXHAUSTED);
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));qso_cancel(&q);
    qso_clock_sample cancelled=sample_at(500,500,500,0,true);
    assert(!qso_tx_valid_at(&q,&tx,&cancelled));qso_tx_finished(&q,&tx,&cancelled,true);assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(!tick(&q,499,499,&tx));
    assert(!tick(&q,601,601,&tx));send(&q,30500);
    assert(!tick(&q,61500,60500,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));
    qso_clock_sample failed=sample_at(500,500,500,0,true);
    qso_tx_finished(&q,&tx,&failed,false);assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);send(&q,500);assert(!tick(&q,400,600,&tx));assert(q.state==QSO_CANCELLED);

    qso_t unconfigured;assert(qso_init(&unconfigured,"K1ABC","FN42","W9XYZ",-10,0,2));
    qso_enable(&unconfigured);assert(!unconfigured.enabled);
    assert(!tick(&unconfigured,500,500,&tx));assert(!unconfigured.active);
    q=newq(0,2);qso_enable(&q);
    assert(!tick_sample(&q,500,500,500,21,true,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);
    assert(!tick_sample(&q,500,1501,500,0,true,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);
    assert(!tick_sample(&q,500,500,500,0,false,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);
    assert(!tick_sample(&q,500,500,501,0,true,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);
    assert(tick_sample(&q,500,1500,1500,20,true,&tx));
    qso_clock_sample fresh=sample_at(1500,2500,1500,20,true);
    assert(qso_tx_valid_at(&q,&tx,&fresh));
    qso_clock_sample stale=sample_at(1501,2501,1500,20,true);
    assert(!qso_tx_valid_at(&q,&tx,&stale));
    qso_tx_finished(&q,&tx,&stale,true);assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));
    assert(!tick(&q,1001,751,&tx));assert(q.state!=QSO_CANCELLED && q.active); /* exactly 250 ms skew */
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));
    assert(!tick(&q,1001,750,&tx));assert(q.state==QSO_CANCELLED); /* 251 ms skew */
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));
    assert(!tick_sample(&q,501,501,499,0,true,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(tick(&q,500,500,&tx));
    assert(!tick(&q,501,499,&tx));assert(q.state==QSO_CANCELLED);
    test_repeated_sample_does_not_repeat_reservation();
    assert(!qso_init(&q,"BAD/CALL","FN42","W9XYZ",-10,0,2));
    puts("qso tests passed: exchanges, slot gate, retries, cancellation, time quality, stale/uncertain/jumped clock");
}
