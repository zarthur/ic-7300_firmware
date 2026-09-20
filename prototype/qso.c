#include "qso.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool call_ok(const char *s) {
    size_t n = strlen(s); bool digit=false, letter=false;
    if (n<3 || n>6) return false;
    for (size_t i=0;i<n;i++) {
        if (s[i]>='0' && s[i]<='9') digit=true;
        else if (s[i]>='A' && s[i]<='Z') letter=true;
        else return false;
    }
    /* Standard type-1 call: digit in column 2 or 3, trailing letters only. */
    size_t d = isdigit((unsigned char)s[2]) ? 2 : 1;
    if (!isdigit((unsigned char)s[d]) || n-d-1>3 || n-d-1<1) return false;
    for (size_t i=d+1;i<n;i++) if (s[i]<'A'||s[i]>'Z') return false;
    return digit && letter;
}
static bool grid_ok(const char *s) {
    return strlen(s)==4 && s[0]>='A' && s[0]<='R' && s[1]>='A' && s[1]<='R'
        && s[2]>='0' && s[2]<='9' && s[3]>='0' && s[3]<='9';
}
bool qso_init(qso_t *q,const char *local,const char *grid,const char *peer,int db,int parity,int retries) {
    if (!q || !local || !grid || !peer || !call_ok(local) || !call_ok(peer) || !strcmp(local,peer)
        || !grid_ok(grid) || db < -50 || db > 49 || parity<0 || parity>1 || retries<0 || retries>20) return false;
    memset(q,0,sizeof(*q)); strcpy(q->local,local); strcpy(q->peer,peer); strcpy(q->grid,grid);
    q->report_db=db; q->parity=parity; q->retry_limit=retries;
    q->last_slot=q->last_rx_slot=q->active_slot=-1; q->generation=1;
    return true;
}
void qso_enable(qso_t *q) { if(q->state<QSO_COMPLETE) q->enabled=true; }
void qso_cancel(qso_t *q) { q->enabled=false; q->active=false; q->state=QSO_CANCELLED; q->generation++; }
static bool report_ok(const char *s) {
    return strlen(s)==3 && (s[0]=='-'||s[0]=='+') && isdigit((unsigned char)s[1])
        && isdigit((unsigned char)s[2]) && atoi(s)>=-50 && atoi(s)<=49;
}
bool qso_receive(qso_t *q,const char *message,int64_t slot) {
    char to[12],from[12],body[16],extra; qso_state next=q->state;
    if (!q->enabled || q->active || q->state>=QSO_COMPLETE || slot<0 || slot<=q->last_rx_slot
        || slot!=q->last_slot+1 || slot%2==q->parity || !q->attempts) return false;
    if (sscanf(message,"%11s %11s %15s %c",to,from,body,&extra)!=3
        || strcmp(to,q->local) || strcmp(from,q->peer)) return false;
    if (q->state==QSO_GRID && grid_ok(body)) next=QSO_REPORT;
    else if (q->state==QSO_GRID && report_ok(body)) next=QSO_RREPORT;
    else if (q->state==QSO_REPORT && body[0]=='R' && report_ok(body+1)) next=QSO_RR73;
    else if (q->state==QSO_RREPORT && (!strcmp(body,"RR73") || !strcmp(body,"RRR"))) next=QSO_73;
    if (next==q->state) return false;
    q->state=next; q->attempts=0; q->last_rx_slot=slot; q->generation++;
    return true;
}
bool qso_tick(qso_t *q,int64_t utc,int64_t mono,qso_tx *out) {
    if (utc<0 || mono<0) { qso_cancel(q); return false; }
    if(q->clock_seen) {
        int64_t du=utc-q->last_utc_ms, dm=mono-q->last_mono_ms;
        if(dm<0 || du<0 || llabs(du-dm)>250) { qso_cancel(q); return false; }
    }
    q->clock_seen=true; q->last_utc_ms=utc; q->last_mono_ms=mono;
    int64_t slot=utc/15000, phase=utc%15000;
    if (!q->enabled || q->active || q->state>=QSO_COMPLETE || slot%2!=q->parity
        || slot<=q->last_slot || slot<=q->last_rx_slot || phase<500 || phase>600) return false;
    if (q->attempts>q->retry_limit) { q->state=QSO_EXHAUSTED; q->enabled=false; q->generation++; return false; }
    char body[8];
    switch(q->state) {
    case QSO_GRID: snprintf(body,sizeof(body),"%s",q->grid); break;
    case QSO_REPORT: snprintf(body,sizeof(body),"%+03d",q->report_db); break;
    case QSO_RREPORT: snprintf(body,sizeof(body),"R%+03d",q->report_db); break;
    case QSO_RR73: strcpy(body,"RR73"); break;
    case QSO_73: strcpy(body,"73"); break;
    default:return false;
    }
    snprintf(out->text,sizeof(out->text),"%s %s %s",q->peer,q->local,body);
    out->start_utc_ms=slot*15000+500; out->generation=q->generation;
    q->last_slot=q->active_slot=slot; q->attempts++; q->active=true; return true;
}
bool qso_tx_valid(const qso_t *q,const qso_tx *tx) {
    return q->enabled && q->active && tx->generation==q->generation
        && tx->start_utc_ms==q->active_slot*15000+500;
}
void qso_tx_finished(qso_t *q,const qso_tx *tx,bool success) {
    if(!qso_tx_valid(q,tx)) return;
    q->active=false;
    if(!success) { qso_cancel(q); return; }
    if(q->state==QSO_73 || q->state==QSO_RR73) {q->state=QSO_COMPLETE;q->enabled=false;q->generation++;}
}
