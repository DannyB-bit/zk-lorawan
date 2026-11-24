#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define WORKERS 4
#define CONNECTIONS 240
struct counts { atomic_int wakeups, accepts, wouldblock, errors, workers_active; };
static void die(const char *s) { perror(s); _exit(90); }
static int listener(int port) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0), one = 1;
    if (fd < 0) die("socket");
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one))) die("SO_REUSEPORT");
    struct sockaddr_in a = {.sin_family=AF_INET,.sin_port=htons(port),.sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
    if (bind(fd,(struct sockaddr*)&a,sizeof(a)) || listen(fd,128)) die("bind/listen");
    return fd;
}
static void worker(int port, int exclusive, struct counts *c, int shared_fd) {
    int fd=shared_fd>=0?shared_fd:listener(port), ep=epoll_create1(0); struct epoll_event ev={.events=EPOLLIN|(exclusive?EPOLLEXCLUSIVE:0),.data.fd=fd}, out[8];
    if(ep<0 || epoll_ctl(ep,EPOLL_CTL_ADD,fd,&ev)) die("epoll registration");
    atomic_fetch_add(&c->workers_active,1);
    for(;;) {
        int n=epoll_wait(ep,out,8,15000); if(n<0){if(errno==EINTR)continue;die("epoll_wait");}
        if(n==0) _exit(91);
        for(int i=0;i<n;i++) {
            atomic_fetch_add(&c->wakeups,1);
            int accepted_this_wakeup=0;
            for(;;) {
                int s=accept4(fd,0,0,SOCK_NONBLOCK);
                if(s>=0){accepted_this_wakeup++;atomic_fetch_add(&c->accepts,1); char b[16]; (void)read(s,b,sizeof(b)); close(s); continue;}
                if(errno==EAGAIN||errno==EWOULDBLOCK){if(!accepted_this_wakeup)atomic_fetch_add(&c->wouldblock,1);break;}
                if(errno==EINTR) continue;
                atomic_fetch_add(&c->errors,1);
                break;
            }
        }
    }
}
int main(int argc,char **argv) {
    int exclusive=argc>1&&!strcmp(argv[1],"exclusive");
    struct counts *c=mmap(0,sizeof(*c),PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0); if(c==MAP_FAILED)die("mmap");
    int probe=listener(0); struct sockaddr_in a; socklen_t al=sizeof(a); if(getsockname(probe,(struct sockaddr*)&a,&al))die("getsockname"); int port=ntohs(a.sin_port); close(probe);
    int shared_fd=exclusive?-1:listener(port);
    pid_t pids[WORKERS]; for(int i=0;i<WORKERS;i++){pids[i]=fork();if(!pids[i])worker(port,exclusive,c,shared_fd);if(pids[i]<0)die("fork");}
    for(int i=0;i<100&&atomic_load(&c->workers_active)<WORKERS;i++){struct timespec t={0,10000000};nanosleep(&t,0);}
    for(int i=0;i<CONNECTIONS;i++) {
        int s=socket(AF_INET,SOCK_STREAM,0),one=1;setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
        a.sin_port=htons(port);a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);a.sin_family=AF_INET;
        if(connect(s,(struct sockaddr*)&a,sizeof(a))) die("connect");
        if(write(s,"x",1)!=1) die("write");
        close(s);
    }
    for(int i=0;i<500&&atomic_load(&c->accepts)<CONNECTIONS;i++){struct timespec t={0,10000000};nanosleep(&t,0);}
    for(int i=0;i<WORKERS;i++) kill(pids[i],SIGKILL);
    for(int i=0;i<WORKERS;i++) while(waitpid(pids[i],0,0)<0&&errno==EINTR){}
    int w=atomic_load(&c->wakeups),ac=atomic_load(&c->accepts),wb=atomic_load(&c->wouldblock),er=atomic_load(&c->errors);
    printf("MODE=%s CONNECTIONS=%d WAKEUPS=%d ACCEPTS=%d EWOULDBLOCK=%d ERRORS=%d\n",exclusive?"EPOLLEXCLUSIVE":"LEGACY",CONNECTIONS,w,ac,wb,er);
    if(ac!=CONNECTIONS||er)return 2;
    if(exclusive&&wb!=0){puts("FAIL: exclusive registration still produced spurious empty wakeups");return 3;}
    if(!exclusive&&wb==0){puts("FAIL: negative control did not expose thundering herd");return 4;}
    puts(exclusive?"EPOLL_EXCLUSIVE_PASS=YES":"LEGACY_HERD_REPRODUCED=YES");return 0;
}
