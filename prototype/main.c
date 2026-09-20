#define _POSIX_C_SOURCE 200809L
#include "codec.h"
#include "qso.h"
#include "alloc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <sys/resource.h>
static double seconds(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static unsigned u16(const unsigned char *b){return b[0]|(unsigned)b[1]<<8;}
static uint32_t u32(const unsigned char *b){return u16(b)|(uint32_t)u16(b+2)<<16;}
static void put16(FILE *f,unsigned n){fputc(n&255,f);fputc(n>>8&255,f);}
static void put32(FILE *f,uint32_t n){put16(f,n);put16(f,n>>16);}
static bool wav_header(FILE *f,size_t *samples){
    unsigned char b[16];bool fmt=false;
    if(fread(b,1,12,f)!=12||memcmp(b,"RIFF",4)||memcmp(b+8,"WAVE",4))return false;
    uint32_t remaining=u32(b+4);if(remaining<4||remaining>4*1024*1024)return false;remaining-=4;
    while(remaining>=8 && fread(b,1,8,f)==8){
        uint32_t n=u32(b+4),padded=n+(n&1);remaining-=8;
        if(padded<n||padded>remaining)return false;
        if(!memcmp(b,"fmt ",4)){
            if(n<16||fread(b,1,16,f)!=16)return false;
            if(u16(b)!=1||u16(b+2)!=1||u32(b+4)!=12000||u32(b+8)!=24000||u16(b+12)!=2||u16(b+14)!=16)return false;
            if(fseek(f,padded-16,SEEK_CUR))return false;fmt=true;
        }else if(!memcmp(b,"data",4)){
            if(!fmt||n%2||!n||n>FT8_SLOT_SAMPLES*2)return false;*samples=n/2;return true;
        }else if(fseek(f,padded,SEEK_CUR))return false;
        remaining-=padded;
    }return false;
}
static void show(const ft8_decoded *d,void *unused){(void)unused;
    /* Codec message alphabet excludes JSON quotes/backslashes. */
    printf("{\"message\":\"%s\",\"frequency_hz\":%.3f,\"time_offset_s\":%.3f,\"sync_score\":%d,\"slot_utc_ms\":%lld}\n",d->text,d->frequency_hz,d->time_offset_s,d->sync_score,(long long)d->slot_utc_ms);
}
static int decode(const char *path){
    FILE *f=fopen(path,"rb");size_t count;if(!f)return 2;
    if(!wav_header(f,&count)){fclose(f);fputs("Expected bounded 12 kHz mono PCM16 WAV\n",stderr);return 2;}
    ft8_rx rx;ft8_rx_init(&rx,0);float samples[960];size_t done=0;
    while(done<count){size_t n=count-done;if(n>960)n=960;
        for(size_t i=0;i<n;i++){unsigned char b[2];if(fread(b,1,2,f)!=2){ft8_rx_free(&rx);fclose(f);return 2;}samples[i]=(int16_t)u16(b)/32768.f;}
        if(!ft8_rx_push(&rx,samples,n,done)){ft8_rx_free(&rx);fclose(f);return 2;}done+=n;
    }
    fclose(f);double start=seconds();int n=ft8_rx_finish(&rx,show,NULL);double decode_s=seconds()-start;
    printf("{\"decoded_count\":%d,\"post_capture_decode_seconds\":%.6f,\"waterfall_bytes\":%d,\"rx_context_bytes\":%zu}\n",n,decode_s,rx.monitor.wf.max_blocks*rx.monitor.wf.block_stride, sizeof(rx));
    ft8_rx_free(&rx);return 0;
}
static int generate(const char *text,const char *path,float hz){
    ft8_tx tx;if(!ft8_tx_init(&tx,text,hz)){fputs("Invalid FT8 message/frequency\n",stderr);return 2;}
    FILE *f=fopen(path,"wb");if(!f)return 2;
    fwrite("RIFF",1,4,f);put32(f,36+FT8_SLOT_SAMPLES*2);fwrite("WAVEfmt ",1,8,f);put32(f,16);put16(f,1);put16(f,1);put32(f,12000);put32(f,24000);put16(f,2);put16(f,16);fwrite("data",1,4,f);put32(f,FT8_SLOT_SAMPLES*2);
    for(int i=0;i<6000;i++)put16(f,0); // waveform starts 0.5 s into slot
    float samples[960];size_t n;
    while((n=ft8_tx_pull(&tx,samples,960)))for(size_t i=0;i<n;i++)put16(f,(uint16_t)(int16_t)lrintf(samples[i]*16000));
    for(int i=6000+FT8_SIGNAL_SAMPLES;i<FT8_SLOT_SAMPLES;i++)put16(f,0);
    bool failed=ferror(f);if(fclose(f))failed=true;
    printf("{\"tx_context_bytes\":%zu,\"samples\":%d}\n",sizeof(tx),FT8_SIGNAL_SAMPLES);return failed?2:0;
}
static int simulate(void){
    qso_t q;qso_tx tx;if(!qso_init(&q,"K1ABC","FN42","W9XYZ",-10,0,2))return 2;qso_enable(&q);
    for(int step=0;step<3;step++){
        if(!qso_tick(&q,500+step*30000,500+step*30000,&tx))return 2;
        printf("TX @ %lld ms: %s\n",(long long)tx.start_utc_ms,tx.text);
        qso_tx_finished(&q,&tx,true);
        if(step<2){const char *rx=step?"K1ABC W9XYZ RR73":"K1ABC W9XYZ -12";printf("RX: %s\n",rx);if(!qso_receive(&q,rx,1+step*2))return 2;}
    }return q.state==QSO_COMPLETE?0:2;
}
int main(int argc,char **argv){
    double start=seconds();int result=2;
    if(argc==3&&!strcmp(argv[1],"decode"))result=decode(argv[2]);
    else if((argc==4||argc==5)&&!strcmp(argv[1],"generate")){
        char *end=NULL;float hz=argc==5?strtof(argv[4],&end):1000;
        if(argc==5&&(!end||*end))return 2;result=generate(argv[2],argv[3],hz);
    }else if(argc==2&&!strcmp(argv[1],"simulate"))result=simulate();
    else fputs("Usage: ft8_proto decode FILE.wav | generate 'MESSAGE' FILE.wav [Hz] | simulate\n",stderr);
    struct rusage usage;getrusage(RUSAGE_SELF,&usage);
    printf("{\"elapsed_seconds\":%.6f,\"codec_peak_heap_bytes\":%zu,\"codec_live_heap_bytes\":%zu,\"maxrss_native\":%ld}\n",seconds()-start,tracked_peak(),tracked_live(),usage.ru_maxrss);
    return result;
}
