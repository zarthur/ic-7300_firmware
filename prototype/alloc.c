#include "alloc.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
typedef union {max_align_t align;size_t n;} header;
static size_t live,peak;
void *tracked_malloc(size_t n) {
    if(n>SIZE_MAX-sizeof(header))abort();
    header *h=malloc(sizeof(*h)+n);
    /* Upstream monitor assumes allocations succeed. Fail explicitly on host. */
    if(!h){fputs("codec allocation failed\n",stderr);abort();}
    h->n=n;live+=n;if(live>peak)peak=live;return h+1;
}
void *tracked_calloc(size_t n,size_t s) {if(s && n>SIZE_MAX/s)abort();void *p=tracked_malloc(n*s);memset(p,0,n*s);return p;}
void tracked_free(void *p) {if(p){header *h=(header*)p-1;live-=h->n;free(h);}}
size_t tracked_peak(void){return peak;}
size_t tracked_live(void){return live;}
