#include "qso.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static qso_t newq(int parity,int retries) { qso_t q; assert(qso_init(&q,"K1ABC","FN42","W9XYZ",-10,parity,retries));return q; }
static qso_tx send(qso_t *q,int64_t t) {qso_tx tx;assert(qso_tick(q,t,t,&tx));assert(qso_tx_valid(q,&tx));qso_tx_finished(q,&tx,true);return tx;}
int main(void) {
    qso_t q=newq(0,2); qso_tx tx;
    assert(!qso_tick(&q,500,500,&tx));qso_enable(&q);
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",1));
    tx=send(&q,500);assert(!strcmp(tx.text,"W9XYZ K1ABC FN42"));
    assert(!qso_tick(&q,501,501,&tx));
    assert(!qso_receive(&q,"K1ABC W1ZZZ -12",1));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",3));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12 extra",1));
    assert(qso_receive(&q,"K1ABC W9XYZ -12",1));
    assert(!qso_receive(&q,"K1ABC W9XYZ -12",1));
    tx=send(&q,30500);assert(!strcmp(tx.text,"W9XYZ K1ABC R-10"));
    assert(qso_receive(&q,"K1ABC W9XYZ RR73",3));
    tx=send(&q,60500);assert(!strcmp(tx.text,"W9XYZ K1ABC 73"));assert(q.state==QSO_COMPLETE);
    assert(!qso_tick(&q,90500,90500,&tx));
    q=newq(1,1);qso_enable(&q);send(&q,15500);
    assert(qso_receive(&q,"K1ABC W9XYZ EN50",2));send(&q,45500);
    assert(qso_receive(&q,"K1ABC W9XYZ R-08",4));send(&q,75500);assert(q.state==QSO_COMPLETE);
    q=newq(0,1);qso_enable(&q);send(&q,500);send(&q,30500);
    assert(!qso_tick(&q,60500,60500,&tx));assert(q.state==QSO_EXHAUSTED);
    q=newq(0,2);qso_enable(&q);assert(qso_tick(&q,500,500,&tx));qso_cancel(&q);
    assert(!qso_tx_valid(&q,&tx));qso_tx_finished(&q,&tx,true);assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(!qso_tick(&q,499,499,&tx));
    assert(!qso_tick(&q,601,601,&tx));send(&q,30500);
    assert(!qso_tick(&q,61500,60500,&tx));assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);assert(qso_tick(&q,500,500,&tx));qso_tx_finished(&q,&tx,false);assert(q.state==QSO_CANCELLED);
    q=newq(0,2);qso_enable(&q);send(&q,500);assert(!qso_tick(&q,400,600,&tx));assert(q.state==QSO_CANCELLED);
    assert(!qso_init(&q,"BAD/CALL","FN42","W9XYZ",-10,0,2));
    puts("qso tests passed: completion, alternate exchange, parity, boundaries, retries, duplicates, cancel, clock jumps");
}
