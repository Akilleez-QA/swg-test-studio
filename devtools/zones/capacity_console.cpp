#include "sharedFoundation/FirstSharedFoundation.h"
#include "sharedNetworkMessages/ConsoleChannelMessages.h"
#include "Archive/ByteStream.h"
#include "serverUtility/ZoneInstanceScope.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>
static bool number(char const *s,bool allowNegative=false)
{ if(!s || !*s || std::strlen(s)>20)return false;if(allowNegative && *s=='-')++s;if(!*s)return false;for(;*s;++s)if(*s<'0'||*s>'9')return false;return true; }
static bool playerWorld(std::string const &scene)
{
    ZoneInstanceScope::Mode const mode=ZoneInstanceScope::mode(scene);
    return mode==ZoneInstanceScope::DynamicArea || mode==ZoneInstanceScope::PilotedSpace || scene=="space_npe_falcon";
}
static bool transfer(int fd,char *p,size_t n,bool write)
{
    while(n)
    {
        ssize_t const count=write ? ::send(fd,p,n,MSG_NOSIGNAL) : ::recv(fd,p,n,0);
        if(count<0 && errno==EINTR)continue;
        if(count<=0) return false;
        p+=count;
        n-=count;
    }
    return true;
}
int main(int argc,char **argv)
{
    if(argc<3) { std::cerr<<"Usage: capacity-console PRIVATE_IPV4 capacityScenes|capacitySample|capacityContent|capacityGroups|capacityLifecycle|capacityFalcon|capacityWake SCENE|capacityGroup ID|capacityDemand GROUP ENTRANT COPY ATTEMPT\n";return 2; }
    std::string command=argv[2];bool valid=false;
    if(argc==3 && (command=="capacityEncounterCensus" || command=="capacityEncounterCensusStatus"))valid=true;
    if(argc==3 && (command=="capacityEncounterBootstrap" || command=="capacityEncounterBootstrapStatus"))valid=true;
    if(argc==3)valid=valid||command=="capacityScenes"||command=="capacitySample"||command=="capacityContent"||command=="capacityGroups"||command=="capacityLifecycle"||command=="capacityFalcon"||command=="capacityInstances"||command=="capacitySaveStatus"||command=="capacityRetireStatus"||command=="capacityRetireOccupiedStatus";
#ifdef SWG_FALCON_FIXTURE
    // Compiled only into the disposable fixture client, never the staged
    // diagnostic console. No caller-supplied script name or command is accepted.
    if(argc==5 && command=="fixtureFalconBurst" && number(argv[3]) && number(argv[4]))
    {
        command="game "+std::string(argv[3])+" runScript fixture.falcon_claim begin "+argv[4];
        argc=3;valid=true;
    }
    if(argc==5 && (command=="fixtureRetirementClaim" || command=="fixtureRetirementClear" || command=="fixtureRetirementExpire" || command=="fixtureRetirementFill") && number(argv[3]) && number(argv[4]))
    {
        command="game "+std::string(argv[3])+" runScript fixture.retirement_claim "+
            (command=="fixtureRetirementClaim"?"begin ":command=="fixtureRetirementClear"?"clear ":command=="fixtureRetirementFill"?"fill ":"expire ")+argv[4];
        argc=3;valid=true;
    }
    if(argc==4 && command=="fixtureRetirementReload" && number(argv[3]))
    {
        command="game "+std::string(argv[3])+" reloadScript fixture.retirement_claim";
        argc=3;valid=true;
    }
    if(argc==4 && command=="fixtureInstanceSelect" && number(argv[3]))
    {
        command="game "+std::string(argv[3])+" runScript fixture.falcon_claim select space_npe_falcon";
        argc=3;valid=true;
    }
#endif
    if(argc==4 && (command=="capacityWake" || command=="capacityInstanceWake"))
    {
        std::string scene=argv[3]; valid=!scene.empty() && scene.size()<=64 && scene.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")==std::string::npos;
    }
    if(argc==5 && command=="capacitySaveProbe")
    {
        std::string scene=argv[3];valid=number(argv[4]) &&
            playerWorld(scene);
    }
    if(argc==5 && command=="capacityRetireEmpty")valid=playerWorld(argv[3]) && number(argv[4]);
    if(argc==5 && command=="capacityRetireOccupied")valid=(std::string(argv[3])=="kashyyyk_rryatt_trail" || std::string(argv[3])=="space_ord_mantell" ||
        (ZoneInstanceScope::mode(argv[3])==ZoneInstanceScope::DynamicArea && !ZoneInstanceScope::playerFamily(argv[3]).empty())) && number(argv[4]);
    if(argc==4 && command=="capacityGroup")valid=number(argv[3]);
    if(argc==7 && command=="capacityDemand")valid=number(argv[3])&&number(argv[4])&&number(argv[5],true)&&number(argv[6]);
    if(!valid){std::cerr<<"Only typed capacity diagnostics, wake and explicit reviewed-world retirement requests are allowed\n";return 2;}
    for(int i=3;i<argc;++i)command+=" "+std::string(argv[i]);
    sockaddr_in address;std::memset(&address,0,sizeof address);address.sin_family=AF_INET;address.sin_port=htons(61000);
    if(inet_pton(AF_INET,argv[1],&address.sin_addr)!=1)return 2;
    unsigned long const ip=ntohl(address.sin_addr.s_addr);
    if((ip>>24)!=127 && (ip>>24)!=10 && (ip>>20)!=0xac1 && (ip>>16)!=0xc0a8)
    {std::cerr<<"Use the private CentralServer IPv4; never publish its console port\n";return 2;}
    int const fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)return 1;
    timeval timeout;timeout.tv_sec=5;timeout.tv_usec=0;
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof timeout);setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof timeout);
    if(connect(fd,reinterpret_cast<sockaddr*>(&address),sizeof address)!=0){perror("connect");close(fd);return 1;}
    ConGenericMessage message(command,1);Archive::ByteStream payload,frame;message.pack(payload);
    Archive::put(frame,static_cast<int>(payload.getSize()));frame.put(payload.getBuffer(),payload.getSize());
    bool ok=transfer(fd,reinterpret_cast<char*>(const_cast<unsigned char*>(frame.getBuffer())),frame.getSize(),true);
    for(unsigned int packets=0;ok && packets<16;++packets)
    {
        unsigned char header[4];if(!transfer(fd,reinterpret_cast<char*>(header),4,false))break;
        unsigned int const size=static_cast<unsigned int>(header[0])|(static_cast<unsigned int>(header[1])<<8)|(static_cast<unsigned int>(header[2])<<16)|(static_cast<unsigned int>(header[3])<<24);
        // TcpClient::checkKeepalive emits a zero-length frame. It carries no
        // envelope and can precede an asynchronous console reply.
        if(size==0)continue;
        if(size<6 || size>2*1024*1024)break;
        std::vector<char> buffer(size);if(!transfer(fd,&buffer[0],size,false))break;
        Archive::ByteStream bytes;bytes.put(&buffer[0],size);Archive::ReadIterator reader=bytes.begin();GameNetworkMessage envelope(reader);
        if(envelope.isType(ConGenericMessage::MessageType))
        {reader=bytes.begin();ConGenericMessage response(reader);std::cout<<response.getMsg()<<"\n";close(fd);return 0;}
    }
    close(fd);std::cerr<<"No complete console response within bounds\n";return 1;
}
