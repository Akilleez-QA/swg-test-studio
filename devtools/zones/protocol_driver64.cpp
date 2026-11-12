// Fixture-only protocol peer. Reuses production serializers; no Windows code.
#include "ProtocolCompanionRoster.h"
#include "sharedFoundation/FirstSharedFoundation.h"
#include "sharedDebug/SetupSharedDebug.h"
#include "sharedFoundation/SetupSharedFoundation.h"
#include "sharedFoundation/ConfigFile.h"
#include "sharedFoundation/Clock.h"
#include "sharedFoundation/Os.h"
#include "sharedFoundation/Crc.h"
#include "sharedFoundation/NetworkId.h"
#include "sharedFoundation/GameControllerMessage.h"
#include "sharedFile/SetupSharedFile.h"
#include "sharedThread/SetupSharedThread.h"
#include "sharedRandom/SetupSharedRandom.h"
#include "sharedNetwork/SetupSharedNetwork.h"
#include "sharedNetwork/NetworkHandler.h"
#include "sharedNetwork/Connection.h"
#include "sharedNetwork/NetworkSetupData.h"
#include "sharedNetworkMessages/ControllerMessageFactory.h"
#include "sharedNetworkMessages/MessageQueueCommandQueueEnqueue.h"
#include "sharedNetworkMessages/MessageQueueCommandQueueRemove.h"
#include "sharedNetworkMessages/MessageQueueStartNpcConversation.h"
#include "sharedNetworkMessages/MessageQueueStringList.h"
#include "StringId.h"
#include "sharedGame/OutOfBandPackager.h"
#include "localizationArchive/StringIdArchive.h"
#include "StringId.h"
#include "sharedNetworkMessages/ClientLoginMessages.h"
#include "sharedNetworkMessages/ClientCentralMessages.h"
#include "sharedNetworkMessages/LoginEnumCluster.h"
#include "sharedNetworkMessages/LoginClusterStatus.h"
#include "sharedNetworkMessages/ClientPermissionsMessage.h"
#include "sharedNetworkMessages/CommandChannelMessages.h"
#include "sharedNetworkMessages/SceneChannelMessages.h"
#include "sharedNetworkMessages/NewbieTutorialResponse.h"
#include "sharedNetworkMessages/CreateProjectileMessage.h"
#include "sharedNetworkMessages/ObjectChannelMessages.h"
#include "sharedNetworkMessages/MessageQueueTeleportAck.h"
#include "sharedNetworkMessages/MessageQueueDataTransform.h"
#include "sharedNetworkMessages/MessageQueueDataTransformWithParent.h"
#include "sharedNetworkMessages/MessageQueueObjectMenuRequest.h"
#include "sharedNetworkMessages/ObjectMenuSelectMessage.h"
#include "sharedNetworkMessages/SuiCreatePageMessage.h"
#include "sharedNetworkMessages/SuiEventNotification.h"
#include "sharedNetworkMessages/LogoutMessage.h"
#include "sharedNetworkMessages/ChatSystemMessage.h"
#include "sharedNetworkMessages/ErrorMessage.h"
#include "sharedNetworkMessages/MessageQueueSecureTrade.h"
#include "sharedNetworkMessages/SecureTradeMessages.h"
#include "sharedNetworkMessages/ChatAvatarId.h"
#include "sharedNetworkMessages/ChatInstantMessageToCharacter.h"
#include "sharedNetworkMessages/ChatInstantMessageToClient.h"
#include "sharedNetworkMessages/ChatOnSendInstantMessage.h"
#include "sharedGame/SuiWidgetProperty.h"
#include "sharedGame/SuiEventType.h"
#include "UnicodeUtils.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sstream>
#include <map>
#include <set>
#include <memory>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>

namespace {
std::string quote(std::string const &value) {
    std::string out="\"";char escaped[8];
    for(size_t i=0;i<value.size();++i) {
        unsigned char c=static_cast<unsigned char>(value[i]);
        if(c=='"'||c=='\\') {out+='\\';out+=c;}
        else if(c<32) {std::sprintf(escaped,"\\u%04x",c);out+=escaped;}
        else out+=c;
    }
    return out+'"';
}
void event(char const *name,std::string const &fields="") {
    std::printf("DRIVER {\"schema_version\":1,\"event\":%s%s%s}\n",quote(name).c_str(),fields.empty()?"":",",fields.c_str());std::fflush(stdout);
}
double seconds() {timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1.e9;}
bool identifier(std::string const &s) {return !s.empty() && s.size()<=48 && s.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_")==std::string::npos;}
bool number(std::string s) {if(s.empty()||s.size()>20)return false;if(s[0]=='-')s.erase(0,1);return !s.empty() && s.find_first_not_of("0123456789")==std::string::npos;}
class Driver;
// Read only the production controller header before choosing a supported payload.
// Other gameplay controllers belong to the graphical client and are not decoded.
class ControllerHeader:public GameNetworkMessage {
public:
    ControllerHeader(Archive::ReadIterator &reader):GameNetworkMessage("ObjControllerMessage"),flags(0),message(0),id(NetworkId::cms_invalid),value(0) {
        addVariable(flags);addVariable(message);addVariable(id);addVariable(value);unpack(reader);
    }
    Archive::AutoVariable<uint32> flags;Archive::AutoVariable<int32> message;
    Archive::AutoVariable<NetworkId> id;Archive::AutoVariable<real> value;
};
NetworkSetupData udpSetup() {NetworkSetupData data;data.useTcp=false;return data;}
uint32 const clientControllerFlags=GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER;
// One typed client action (docs/fixture-client-actions.md). Every message is a class of the
// server tree, built as the reference client builds it; nothing here is a free-form command.
struct ClientAction {
    ClientAction():amount(0) {}
    std::string verb;NetworkId target;std::string targetName;std::string text;int amount;
};
// Owns the message (and a controller payload) that one client action sends.
class Outgoing {
public:
    Outgoing():message(0),payload(0) {}
    ~Outgoing() {delete message;delete payload;}
    GameNetworkMessage *message;MessageQueue::Data *payload;std::string command;
private:
    Outgoing(Outgoing const &);Outgoing &operator=(Outgoing const &);
};
bool tellText(std::string const &text) {
    if(text.empty()||text.size()>200||text[0]==' '||text[text.size()-1]==' ')return false;
    for(size_t i=0;i<text.size();++i)if(text[i]<32||text[i]>126)return false;
    return true;
}
// Command-table rows sent through the command queue, exactly as the peer's existing group
// actions send them (MessageQueueCommandQueueEnqueue on CM_commandQueueEnqueue).
char const *queuedCommand(std::string const &verb) {
    static char const *const table[][2]={{"groupInvite","invite"},{"groupJoin","join"},{"groupDecline","decline"},
        {"groupUninvite","uninvite"},{"groupLeave","leaveGroup"},{"groupDisband","disband"},
        {"groupMakeLeader","makeLeader"},{"groupDismiss","dismissGroupMember"}};
    for(size_t i=0;i<sizeof table/sizeof table[0];++i)if(verb==table[i][0])return table[i][1];
    return 0;
}
bool buildClientAction(ClientAction const &a,NetworkId const &character,uint32 sequence,Outgoing &out) {
    if(!character.isValid())return false;
    if(char const *name=queuedCommand(a.verb)) {
        // invite names its target by character name (the peer's existing invite); decline,
        // leave and disband take no target; the others name the companion's object.
        bool const named=a.verb=="groupInvite",untargeted=a.verb=="groupDecline"||a.verb=="groupLeave"||a.verb=="groupDisband";
        if(!untargeted && (!a.target.isValid()||a.targetName.empty()))return false;
        MessageQueueCommandQueueEnqueue *data=new MessageQueueCommandQueueEnqueue(sequence,Crc::normalizeAndCalculate(name),
            named||untargeted?NetworkId::cms_invalid:a.target,named?Unicode::narrowToWide(a.targetName):Unicode::String());
        out.payload=data;out.command=name;
        out.message=new ObjControllerMessage(character,CM_commandQueueEnqueue,0,clientControllerFlags,data);return true;
    }
    // ClientSecureTradeManager: request names the recipient; accept and deny carry no ids.
    MessageQueueSecureTrade::TradeMessageId tmi=MessageQueueSecureTrade::TMI_LastTradeMessageId;NetworkId recipient;
    if(a.verb=="tradeRequest"){if(!a.target.isValid())return false;tmi=MessageQueueSecureTrade::TMI_RequestTrade;recipient=a.target;}
    else if(a.verb=="tradeAccept")tmi=MessageQueueSecureTrade::TMI_AcceptTrade;
    else if(a.verb=="tradeDeny")tmi=MessageQueueSecureTrade::TMI_DeniedTrade;
    if(tmi!=MessageQueueSecureTrade::TMI_LastTradeMessageId) {
        MessageQueueSecureTrade *data=new MessageQueueSecureTrade(tmi,NetworkId::cms_invalid,recipient);
        out.payload=data;out.message=new ObjControllerMessage(character,CM_secureTrade,0,clientControllerFlags,data);return true;
    }
    if(a.verb=="tradeItem"){if(!a.target.isValid())return false;out.message=new AddItemMessage(a.target);return true;}
    if(a.verb=="tradeCredits"){if(a.amount<1||a.amount>1000000)return false;out.message=new GiveMoneyMessage(a.amount);return true;}
    if(a.verb=="tradeOffer"){out.message=new AcceptTransactionMessage();return true;}
    if(a.verb=="tradeUnoffer"){out.message=new UnAcceptTransactionMessage();return true;}
    if(a.verb=="tradeVerify"){out.message=new VerifyTradeMessage();return true;}
    if(a.verb=="tradeReject"){out.message=new DenyTradeMessage();return true;}
    if(a.verb=="tradeCancel"){out.message=new AbortTradeMessage();return true;}
    // CuiInstantMessageManager: a tell is a chat message the connection server forwards to chat.
    // The name alone is given; the chat server completes game code and cluster.
    if(a.verb=="tell"){if(a.targetName.empty()||!tellText(a.text))return false;
        out.message=new ChatInstantMessageToCharacter(sequence,ChatAvatarId(a.targetName),Unicode::narrowToWide(a.text),Unicode::String());return true;}
    return false;
}
char const *tradeMessageName(int id) {
    switch(id){case MessageQueueSecureTrade::TMI_RequestTrade:return "request";case MessageQueueSecureTrade::TMI_TradeRequested:return "requested";
    case MessageQueueSecureTrade::TMI_AcceptTrade:return "accept";case MessageQueueSecureTrade::TMI_DeniedTrade:return "denied";
    case MessageQueueSecureTrade::TMI_DeniedPlayerBusy:return "busy";case MessageQueueSecureTrade::TMI_DeniedPlayerUnreachable:return "unreachable";
    case MessageQueueSecureTrade::TMI_RequestTradeReversed:return "reversed";default:return "unknown";}
}
class Peer:public Connection {
public:
    Peer(Driver &d,bool login,std::string const &host,unsigned short port);
    void onConnectionOpened();void onConnectionClosed();void onReceive(Archive::ByteStream const &bytes);
    void message(GameNetworkMessage const &msg) {Archive::ByteStream bytes;msg.pack(bytes);send(bytes,true);}
    Driver &driver;bool login;
};
struct Driver {
    Driver():login(0),game(0),token(0),cluster(0),listed(false),status(false),enumerated(false),creating(false),selected(false),ready(false),done(false),failed(false),ownBaselines(false),refreshLoading(false),holdArrival(false),sequence(0),expires(0),finishAt(0),loadingAt(0),actionReadyAt(0),shipStamp(0),shipStampAt(0) {}
    ~Driver() {delete game;delete login;delete token;}
    Peer *login,*game;LoginClientToken *token;uint32 cluster;NetworkId character;
    std::string project,account,name;bool listed,status,enumerated,creating,selected,ready,done,failed,ownBaselines,refreshLoading,holdArrival;unsigned int sequence;
    double expires,finishAt,loadingAt,actionReadyAt;std::string input,sceneFields;
    Transform shipTransform;uint32 shipStamp;double shipStampAt;
    std::map<int,SuiPageData> pages;std::map<NetworkId,std::set<unsigned int> > menus;
    std::map<unsigned int,std::string> commands;
    NetworkId conversation,ship;ProtocolCompanionRoster companions;std::vector<std::string> responses;
    void command(std::string const &name,NetworkId const &target,Unicode::String const &args) {
        MessageQueueCommandQueueEnqueue data(++sequence,Crc::normalizeAndCalculate(name.c_str()),target,args);
        commands[sequence]=name;
        ObjControllerMessage msg(character,CM_commandQueueEnqueue,0,GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER,&data);game->message(msg);
    }
    void fail(std::string const &why) {event("failure","\"reason\":"+quote(why));failed=true;done=true;}
    void connectGame() {
        if(game||selected||finishAt||done||!token||!listed||!status||!enumerated)return;
        if(!character.isValid()&&!creating){fail("character missing and creation disabled");return;}
        game=new Peer(*this,false,"connection",45063);
    }
    void opened(Peer &p) {
        if(p.login) {LoginClientId msg(account,"fixture-protocol-driver");p.message(msg);event("login_request");}
        else {ClientIdMsg msg(token->getToken(),token->getTokenSize(),0);p.message(msg);event("game_auth_request");}
    }
    void receive(Peer &p,Archive::ByteStream const &bytes);
    void action(std::string const &line);
    void reply(std::string const &id,std::string const &verb,bool accepted,std::string const &detail) {
        event("reply","\"request\":"+id+",\"verb\":"+quote(verb)+",\"accepted\":"+(accepted?"true":"false")+(detail.empty()?"":","+detail));
    }
    // A held-session request: "@<id> <verb> [companion] [value...]". Exactly one reply event
    // per request; a refused request is reported, not fatal, so the controller tears down.
    void request(std::string const &line) {
        size_t space=line.find(' ');std::string id=line.substr(1,space==std::string::npos?std::string::npos:space-1);
        if(id.empty()||id.size()>6||id[0]=='0'||id.find_first_not_of("0123456789")!=std::string::npos){fail("invalid request id");return;}
        std::string rest=space==std::string::npos?"":line.substr(space+1);std::istringstream in(rest);ClientAction a;std::string target,extra;in>>a.verb;
        if(!ready||!game){reply(id,a.verb,false,"\"reason\":\"session not ready\"");return;}
        bool const takesTarget=a.verb=="groupInvite"||a.verb=="groupJoin"||a.verb=="groupUninvite"||a.verb=="groupMakeLeader"||
            a.verb=="groupDismiss"||a.verb=="tradeRequest"||a.verb=="tell";
        if(takesTarget) {
            if(!(in>>target)||!companions.find(target)){reply(id,a.verb,false,"\"reason\":\"not a roster companion\"");return;}
            a.target=NetworkId(target);a.targetName=*companions.find(target);
        }
        if(a.verb=="tradeItem"){if(!(in>>target)||!number(target)||target[0]=='-'||target=="0"||target.size()>19||(target.size()==19&&target>"9223372036854775807")){reply(id,a.verb,false,"\"reason\":\"invalid item\"");return;}a.target=NetworkId(target);}
        if(a.verb=="tradeCredits"){if(!(in>>target)||!number(target)||target[0]=='-'||target.size()>7){reply(id,a.verb,false,"\"reason\":\"invalid amount\"");return;}a.amount=std::atoi(target.c_str());}
        if(a.verb=="tell"){std::getline(in,a.text);if(!a.text.empty()&&a.text[0]==' ')a.text.erase(0,1);}
        else if(in>>extra){reply(id,a.verb,false,"\"reason\":\"unexpected argument\"");return;}
        Outgoing out;unsigned int const seq=++sequence;
        if(!buildClientAction(a,character,seq,out)){reply(id,a.verb,false,"\"reason\":\"invalid client action\"");return;}
        if(!out.command.empty())commands[seq]=out.command;
        game->message(*out.message);
        std::ostringstream detail;detail<<"\"sequence\":"<<seq;
        if(a.target.isValid())detail<<",\"target\":"<<quote(a.target.getValueString());
        reply(id,a.verb,true,detail.str());
    }
    void tick() {
        if(seconds()>expires){fail("session deadline");return;}
        if(finishAt && seconds()>=finishAt){done=true;return;}
        if(game && !holdArrival && !ready && ownBaselines && loadingAt && seconds()>=loadingAt) {
            NewbieTutorialResponse loaded("clientReady");game->message(loaded);ready=true;loadingAt=0;
            event("scene_ready",sceneFields);
        }
        if(actionReadyAt && ready && seconds()>=actionReadyAt) {
            // A same-world setup teleport may retain the scene. Complete its
            // loading screen too, rather than leaving server loading protection.
            if(refreshLoading){NewbieTutorialResponse loaded("clientReady");game->message(loaded);refreshLoading=false;}
            actionReadyAt=0;event("action_ready",sceneFields);
        }
        char buffer[1024];ssize_t n=read(STDIN_FILENO,buffer,sizeof buffer);
        if(n>0) {input.append(buffer,n);if(input.size()>4096){fail("input bound");return;}}
        else if(n==0&&!finishAt){finishAt=seconds()+2;if(game)game->disconnect();event("input_closed");}
        size_t end;
        while(!done && (end=input.find('\n'))!=std::string::npos){std::string line=input.substr(0,end);input.erase(0,end+1);if(!line.empty()&&line[0]=='@')request(line);else action(line);}
    }
};
Peer::Peer(Driver &d,bool isLogin,std::string const &host,unsigned short port):Connection(host,port,udpSetup()),driver(d),login(isLogin) {}
void Peer::onConnectionOpened(){driver.opened(*this);}
void Peer::onConnectionClosed(){
    // NetworkHandler owns deletion of disconnected peers. Clear borrowed handles
    // before its deferred destruction so Driver cannot delete the peer twice.
    if(login)driver.login=0;else driver.game=0;
    event(login?"login_closed":"game_closed");if(!login&&!driver.finishAt)driver.fail("unexpected game disconnect");
}
void Peer::onReceive(Archive::ByteStream const &bytes){try{driver.receive(*this,bytes);}catch(...){driver.fail("malformed server message");}}
void Driver::receive(Peer &p,Archive::ByteStream const &bytes) {
    Archive::ReadIterator reader=bytes.begin();GameNetworkMessage envelope(reader);reader=bytes.begin();
    if(envelope.isType("ErrorMessage")){ErrorMessage msg(reader);fail("server error: "+msg.getErrorName()+" "+msg.getDescription());return;}
    if(p.login) {
        if(envelope.isType("LoginClientToken")){if(token){fail("duplicate login token");return;}token=new LoginClientToken(reader);event("authenticated","\"station_id\":"+quote(NetworkId(static_cast<int64>(token->getStationId())).getValueString()));}
        else if(envelope.isType("LoginEnumCluster")) {
            LoginEnumCluster msg(reader);unsigned int matches=0;
            for(size_t i=0;i<msg.getData().size();++i)if(msg.getData()[i].m_clusterName==project){cluster=msg.getData()[i].m_clusterId;++matches;}
            if(matches!=1){fail("exact fixture cluster not found");return;}listed=true;
        } else if(envelope.isType("LoginClusterStatus")) {
            LoginClusterStatus msg(reader);
            for(size_t i=0;i<msg.getData().size();++i)if(listed&&msg.getData()[i].m_clusterId==cluster){
                if(msg.getData()[i].m_connectionServerAddress!="127.0.0.1"||msg.getData()[i].m_connectionServerPort!=45063){fail("unexpected advertised game endpoint");return;}status=true;
            }
        } else if(envelope.isType("EnumerateCharacterId")) {
            EnumerateCharacterId msg(reader);unsigned int matches=0;
            for(size_t i=0;i<msg.getData().size();++i){
                EnumerateCharacterId::Chardata const &c=msg.getData()[i];
                if(c.m_clusterId!=cluster||Unicode::wideToNarrow(c.m_name)!=name){fail("account contains an unexpected character");return;}
                character=c.m_networkId;++matches;
            }
            if(matches>1){fail("duplicate character identity");return;}enumerated=true;event("characters","\"count\":"+quote(matches?"1":"0")+",\"character\":"+quote(character.getValueString()));
        }
        connectGame();return;
    }
    if(envelope.isType("ClientPermissionsMessage")) {
        ClientPermissionsMessage msg(reader);if(!msg.getCanLogin()){fail("login denied");return;}
        if(selected){fail("duplicate permissions");return;}selected=true;
        if(character.isValid()){SelectCharacter select(character);p.message(select);event("character_selected","\"character\":"+quote(character.getValueString()));}
        else {
            if(!creating||!msg.getCanCreateRegularCharacter()){fail("character creation denied");return;}
            ClientCreateCharacter create(Unicode::narrowToWide(name),"object/creature/player/human_male.iff",1.0f,"mos_eisley","","","","combat_brawler",false,Unicode::String(),true,"smuggler_1a","combat_brawler_novice");
            p.message(create);event("creation_requested");
        }
    } else if(envelope.isType("ClientCreateCharacterFailed")){ClientCreateCharacterFailed msg(reader);fail("creation rejected: "+msg.getErrorMessage().getCanonicalRepresentation());}
    else if(envelope.isType("ClientCreateCharacterSuccess")){ClientCreateCharacterSuccess msg(reader);if(character.isValid()||!creating){fail("unsolicited created character");return;}character=msg.getNetworkId();SelectCharacter select(character);p.message(select);event("created","\"character\":"+quote(character.getValueString()));}
    else if(envelope.isType("CmdStartScene")) {
        CmdStartScene msg(reader);if(msg.getObjectId()!=character){fail("scene character mismatch");return;}
        if(!holdArrival){CmdSceneReady response;p.message(response);}ready=false;ownBaselines=false;refreshLoading=false;loadingAt=0;if(actionReadyAt)actionReadyAt=seconds()+1;pages.clear();menus.clear();responses.clear();conversation=NetworkId::cms_invalid;Vector const &v=msg.getStartPosition();char position[160];::snprintf(position,sizeof position,"[%.9g,%.9g,%.9g]",v.x,v.y,v.z);
        sceneFields="\"character\":"+quote(character.getValueString())+",\"scene\":"+quote(msg.getSceneName())+",\"position\":"+position;
        event("scene_started",sceneFields);
    } else if(envelope.isType("CmdSceneReady")) {
        event("server_scene_ready",std::string("\"baselines\":")+(ownBaselines?"true":"false")+",\"ready\":"+(ready?"true":"false"));
        if(!ready && !sceneFields.empty())loadingAt=seconds()+1;
    } else if(envelope.isType("SceneEndBaselines")) {
        SceneEndBaselines msg(reader);
        if(msg.getNetworkId()==character) event("character_baselines_observed",std::string("\"ready\":")+(ready?"true":"false"));
        if(msg.getNetworkId()==character && !ownBaselines){ownBaselines=true;event("character_baselines");}
    } else if(envelope.isType("ObjControllerMessage")) {
        ControllerHeader header(reader);
        if(header.message.get()!=CM_netUpdateTransform && header.message.get()!=CM_netUpdateTransformWithParent && header.message.get()!=CM_objectMenuResponse && header.message.get()!=CM_npcConversationStart && header.message.get()!=CM_npcConversationResponses && header.message.get()!=CM_commandQueueRemove && header.message.get()!=CM_secureTrade)return;
        reader=bytes.begin();
        ObjControllerMessage msg(reader);
        std::auto_ptr<MessageQueue::Data> owned(msg.getData());
        MessageQueueCommandQueueRemove const *result=dynamic_cast<MessageQueueCommandQueueRemove const *>(msg.getData());
        if(result && msg.getNetworkId()==character) {
            std::ostringstream fields;fields<<"\"command\":"<<quote(commands[result->getSequenceId()])<<",\"status\":"<<result->getStatus()<<",\"detail\":"<<result->getStatusDetail()<<",\"sequence\":"<<result->getSequenceId();
            commands.erase(result->getSequenceId());event("command_result",fields.str());
        }
        // CreatureController::tradeRequested / handleSecureTradeMessage and
        // ServerSecureTradeManager::refuseTrade answer on CM_secureTrade.
        MessageQueueSecureTrade const *trade=dynamic_cast<MessageQueueSecureTrade const *>(msg.getData());
        if(trade && msg.getNetworkId()==character)
            event("secure_trade","\"trade\":"+quote(tradeMessageName(trade->getTradeMessageId()))+",\"initiator\":"+quote(trade->getInitiator().getValueString())+",\"recipient\":"+quote(trade->getRecipient().getValueString()));
        MessageQueueStartNpcConversation const *start=dynamic_cast<MessageQueueStartNpcConversation const *>(msg.getData());
        if(start && msg.getNetworkId()==character) {conversation=start->getNpc();responses.clear();event("conversation_started","\"target\":"+quote(conversation.getValueString()));}
        MessageQueueStringList const *options=dynamic_cast<MessageQueueStringList const *>(msg.getData());
        if(options && msg.getNetworkId()==character) {
            responses.clear();std::string items="[";
            for(int i=0;i<options->getStringCount();++i) {
                Unicode::String const &text=options->getString(i);std::string key;
                size_t split=text.find(static_cast<unsigned short>(0));
                if(split!=Unicode::String::npos) {
                    // Read the OOB header and leading ProsePackage StringId.
                    // The remaining prose belongs to graphical localization.
                    Unicode::String oob=text.substr(split+1);
                    Archive::ByteStream packed(reinterpret_cast<unsigned char const *>(oob.data()),oob.size()*sizeof(Unicode::unicode_char_t));
                    Archive::ReadIterator fields=packed.begin();unsigned short padding=0;unsigned char type=0;int position=0;
                    Archive::get(fields,padding);Archive::get(fields,type);Archive::get(fields,position);
                    if(type==OutOfBandPackager::OT_prosePackage && padding<=1) {StringId id;Archive::get(fields,id);key=id.getCanonicalRepresentation();}
                }
                if(key.empty())key=Unicode::wideToNarrow(text);
                responses.push_back(key);if(i)items+=",";items+=quote(key);
            }
            event("conversation_responses","\"target\":"+quote(conversation.getValueString())+",\"responses\":"+items+"]");
        }
        if((msg.getNetworkId()==character || (ship.isValid() && msg.getNetworkId()==ship)) && (msg.getMessage()==CM_netUpdateTransform||msg.getMessage()==CM_netUpdateTransformWithParent)) {
            unsigned int seq=0;bool found=false;
            MessageQueueDataTransform const *plain=dynamic_cast<MessageQueueDataTransform const *>(msg.getData());
            MessageQueueDataTransformWithParent const *parent=dynamic_cast<MessageQueueDataTransformWithParent const *>(msg.getData());
            if(plain){seq=plain->getSequenceNumber();found=true;if(msg.getNetworkId()==ship){shipTransform=plain->getTransform();shipStamp=plain->getSyncStamp();shipStampAt=seconds();}}if(parent){seq=parent->getSequenceNumber();found=true;}
            if(found){MessageQueueTeleportAck ack(seq);ObjControllerMessage response(msg.getNetworkId(),CM_teleportAck,0,GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER,&ack);p.message(response);event("teleport_ack","\"object\":"+quote(msg.getNetworkId().getValueString()));}
        }
        MessageQueueObjectMenuRequest const *menu=dynamic_cast<MessageQueueObjectMenuRequest const *>(msg.getData());
        if(menu&&menu->getRequestorId()==character) {
            if(menus.size()>=32){fail("menu bound");return;}std::string items="[";
            for(size_t i=0;i<menu->getData().size();++i){ObjectMenuRequestData const &r=menu->getData()[i];if(i)items+=",";char number[32];std::sprintf(number,"%u",r.m_menuItemType);items+="{\"type\":"+std::string(number)+",\"label\":"+quote(Unicode::wideToNarrow(r.m_label))+"}";if(r.isEnabled()&&!r.isOutOfRange())menus[menu->getTargetId()].insert(r.m_menuItemType);}
            event("menu","\"target\":"+quote(menu->getTargetId().getValueString())+",\"items\":"+items+"]");
        }
    } else if(envelope.isType(SuiCreatePageMessage::MessageType)) {
        SuiCreatePageMessage msg(reader);SuiPageData const &page=msg.getPageData();if(pages.size()>=32){fail("page bound");return;}pages[page.getPageId()]=page;
        std::ostringstream fields;fields<<"\"page\":"<<page.getPageId()<<",\"name\":"<<quote(page.getPageName())<<",\"properties\":[";bool comma=false;
        for(size_t i=0;i<page.getCommands().size();++i){SuiCommand const &cmd=page.getCommands()[i];if(cmd.getType()==SuiCommand::SCT_setProperty){std::string prop;Unicode::String value;cmd.getSetProperty(prop,value);if(comma)fields<<",";comma=true;fields<<"{\"widget\":"<<quote(cmd.getTargetWidget())<<",\"property\":"<<quote(prop)<<",\"value\":"<<quote(Unicode::wideToNarrow(value))<<"}";}}
        fields<<"]";event("sui",fields.str());
    } else if(envelope.isType("ChatSystemMessage")) {
        ChatSystemMessage msg(reader);std::string key;Unicode::String const &oob=msg.getOutOfBand();
        if(oob.size()>=4) {
            Archive::ByteStream packed(reinterpret_cast<unsigned char const *>(oob.data()),oob.size()*sizeof(Unicode::unicode_char_t));
            Archive::ReadIterator fields=packed.begin();unsigned short padding=0;unsigned char type=0;int position=0;
            Archive::get(fields,padding);Archive::get(fields,type);Archive::get(fields,position);
            if(padding<=1 && (type==OutOfBandPackager::OT_prosePackage || type==OutOfBandPackager::OT_stringId)) {
                StringId id;Archive::get(fields,id);key=id.getCanonicalRepresentation();
            }
        }
        event("system_message","\"text\":"+quote(Unicode::wideToNarrow(msg.getMessage()))+",\"string_id\":"+quote(key));
    }
    // ServerSecureTrade sends these to one or both traders (beginTrading, addItem, giveMoney,
    // acceptOffer, unacceptOffer, beginVerification, verifyTrade, rejectOffer, completeTrade, cancelTrade).
    else if(envelope.isType("BeginTradeMessage")){BeginTradeMessage msg(reader);event("trade_begun","\"partner\":"+quote(msg.getPlayerId().getValueString()));}
    else if(envelope.isType("AddItemMessage")){AddItemMessage msg(reader);event("trade_item_added","\"item\":"+quote(msg.getNetworkId().getValueString()));}
    else if(envelope.isType(AddItemFailedMessage::MessageType)){AddItemFailedMessage msg(reader);event("trade_item_failed","\"item\":"+quote(msg.getNetworkId().getValueString()));}
    else if(envelope.isType("RemoveItemMessage")){RemoveItemMessage msg(reader);event("trade_item_removed","\"item\":"+quote(msg.getNetworkId().getValueString()));}
    else if(envelope.isType("GiveMoneyMessage")){GiveMoneyMessage msg(reader);std::ostringstream f;f<<"\"amount\":"<<msg.getAmount();event("trade_credits",f.str());}
    else if(envelope.isType("AcceptTransactionMessage"))event("trade_offer_accepted");
    else if(envelope.isType("UnAcceptTransactionMessage"))event("trade_offer_withdrawn");
    else if(envelope.isType("BeginVerificationMessage"))event("trade_verification");
    else if(envelope.isType("VerifyTradeMessage"))event("trade_verified");
    else if(envelope.isType("DenyTradeMessage"))event("trade_rejected");
    else if(envelope.isType("TradeCompleteMessage"))event("trade_complete");
    else if(envelope.isType("AbortTradeMessage"))event("trade_aborted");
    // ChatServer answers a tell with ChatOnSendInstantMessage and delivers ChatInstantMessageToClient.
    else if(envelope.isType("ChatOnSendInstantMessage")){ChatOnSendInstantMessage msg(reader);std::ostringstream f;f<<"\"sequence\":"<<msg.getSequence()<<",\"result\":"<<msg.getResult();event("tell_result",f.str());}
    else if(envelope.isType("ChatInstantMessageToClient")){ChatInstantMessageToClient msg(reader);std::string text=Unicode::wideToNarrow(msg.getMessage());if(text.size()>400)text.resize(400);
        for(size_t i=0;i<text.size();++i)if(text[i]<32||text[i]>126)text[i]='?';
        event("tell_received","\"from\":"+quote(msg.getFromName().name)+",\"text\":"+quote(text));}
    else if(envelope.isType("LogoutMessage")){finishAt=seconds()+2;p.disconnect();event("logout_accepted");}
}
void Driver::action(std::string const &line) {
    std::istringstream in(line);std::string command,target,value,extra;in>>command;
    if(command=="quit" && !(in>>extra)){finishAt=seconds()+2;if(game)game->disconnect();if(login)login->disconnect();event("disconnect_requested");return;}
    if(command=="awaitReady" && !(in>>extra) && game) {actionReadyAt=seconds()+1;refreshLoading=true;return;}
    if(command=="releaseArrival" && !(in>>extra) && game && holdArrival) {
        holdArrival=false;CmdSceneReady response;game->message(response);event("arrival_released");return;
    }
    if(!ready||!game){fail("action before scene ready");return;}
    if(command=="holdArrival" && !(in>>extra) && !holdArrival) {holdArrival=true;event("arrival_held");return;}
#ifndef SWG_STUDIO_PROFILE_RESTORATION
    // The restoration tree's CreateProjectileMessage takes a ship id first; that profile has no ships.
    if(command=="fire" && !(in>>extra) && ship.isValid() && shipStampAt>0) {
        uint32 const stamp=shipStamp+static_cast<uint32>((seconds()-shipStampAt)*1000.0);
        CreateProjectileMessage shot(0,0,0,0,shipTransform,stamp);game->message(shot);event("shot_requested");return;
    }
#endif
    if(command=="trackShip" && (in>>target) && !(in>>extra) && number(target) && target[0]!='-' && (!ship.isValid() || ship==NetworkId(target))) {
        ship=NetworkId(target);event("ship_tracked","\"ship\":"+quote(target));return;
    }
    if((command=="invite"||command=="join"||command=="makeLeader"||command=="dismissGroupMember") && (in>>target) && !(in>>extra) && companions.find(target)) {
        if(command=="invite") this->command(command,NetworkId::cms_invalid,Unicode::narrowToWide(*companions.find(target)));
        else this->command(command,NetworkId(target),Unicode::String());
        event("group_command","\"command\":"+quote(command));return;
    }
    if(command=="attack" && (in>>target) && !(in>>extra) && number(target) && target.size()<=19 && target[0]>='1' && target[0]<='9' &&
        (target.size()<19 || target<="9223372036854775807") && NetworkId(target)!=character) {
        this->command("meleeHit",NetworkId(target),Unicode::String());event("attack_requested","\"target\":"+quote(target));return;
    }
    if(command=="peace" && !(in>>extra)) {
        this->command("peace",NetworkId::cms_invalid,Unicode::String());event("peace_requested");return;
    }
    if(command=="stand" && !(in>>extra)) {
        this->command("stand",NetworkId::cms_invalid,Unicode::String());event("stand_requested");return;
    }
    if(command=="unstick" && !(in>>extra) && game && character.isValid()) {
        this->command("unstick",NetworkId::cms_invalid,Unicode::String());event("unstick_requested");return;
    }
    if((command=="leaveGroup" || command=="disband") && !(in>>extra)) {this->command(command,NetworkId::cms_invalid,Unicode::String());event("group_command","\"command\":"+quote(command));return;}
    if(command=="converse" && (in>>target) && !(in>>extra) && number(target)) {
        // CuiConversationManager closes the active tutorial conversation before
        // opening a different comm target. Preserve that normal command order.
        // A same-world setup can reset this peer's scene before the server
        // clears its old tutorial conversation. Stop is safe when none exists.
        this->command("npcConversationStop",NetworkId::cms_invalid,Unicode::String());
        conversation=NetworkId::cms_invalid;responses.clear();this->command("npcConversationStart",NetworkId(target),Unicode::narrowToWide("0 "));event("conversation_requested");return;
    }
    if(command=="respond" && (in>>target) && !(in>>extra) && conversation.isValid()) {
        for(size_t i=0;i<responses.size();++i)if(responses[i]==target) {
            char index[32];std::sprintf(index,"%u",static_cast<unsigned int>(i));this->command("npcConversationSelect",NetworkId::cms_invalid,Unicode::narrowToWide(index));responses.clear();event("conversation_answered","\"response\":"+quote(target));return;
        }
        fail("conversation response not offered");return;
    }
    if(command=="logout" && !(in>>extra)){
        MessageQueueCommandQueueEnqueue sit(++sequence,Crc::normalizeAndCalculate("sitServer"),NetworkId::cms_invalid,Unicode::String());
        ObjControllerMessage sitMessage(character,CM_commandQueueEnqueue,0,GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER,&sit);
        game->message(sitMessage);
        MessageQueueCommandQueueEnqueue data(++sequence,Crc::normalizeAndCalculate("logoutServer"),NetworkId::cms_invalid,Unicode::String());
        ObjControllerMessage msg(character,CM_commandQueueEnqueue,0,GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER,&data);
        game->message(msg);finishAt=seconds()+60;event("logout_requested");return;
    }
    if(command=="menu" && (in>>target) && !(in>>extra) && number(target)) {
        stdvector<ObjectMenuRequestData>::fwd empty;MessageQueueObjectMenuRequest data(NetworkId(target),character,empty,static_cast<uint8>(++sequence));ObjControllerMessage msg(character,CM_objectMenuRequest,0,GameControllerMessageFlags::SEND|GameControllerMessageFlags::RELIABLE|GameControllerMessageFlags::DEST_AUTH_SERVER,&data);game->message(msg);event("menu_requested","\"target\":"+quote(target));return;
    }
    if(command=="select" && (in>>target>>value) && !(in>>extra) && number(target)&&number(value)) {
        unsigned int item=static_cast<unsigned int>(std::strtoul(value.c_str(),0,10));NetworkId id(target);
        if(item>65535 || !menus[id].count(item)){fail("selection not offered by server");return;}ObjectMenuSelectMessage msg(id,static_cast<uint16>(item));game->message(msg);menus.erase(id);event("menu_selected");return;
    }
    if(command=="answer" && (in>>target>>value) && number(target) && (value=="ok"||value=="cancel")) {
        std::string text;std::getline(in,text);if(!text.empty()&&text[0]==' ')text.erase(0,1);if(text.size()>256){fail("answer bound");return;}
        int id=std::atoi(target.c_str());std::map<int,SuiPageData>::iterator page=pages.find(id);if(page==pages.end()){fail("unknown SUI page");return;}
        int index=0,buttonIndex=-1;SuiCommand const *subscription=0;
        while((subscription=page->second.findSubscribeToEventCommandByIndex(index))!=0){
            std::string widget=subscription->getTargetWidget(),callback;int kind=0;subscription->getSubscribeToEventCallback(kind,callback);
            bool closed=widget.empty() && kind==(value=="ok"?SuiEventType::SET_onClosedOk:SuiEventType::SET_onClosedCancel);
            bool button=kind==SuiEventType::SET_onButton && ((value=="ok"&&(widget=="btnOk"||widget=="btnYes"))||(value=="cancel"&&widget=="btnCancel"));
            if(closed)break;
            if(button && !callback.empty())buttonIndex=index;
            ++index;
        }
        if(!subscription && buttonIndex>=0){index=buttonIndex;subscription=page->second.findSubscribeToEventCommandByIndex(index);}
        if(!subscription){fail("SUI button subscription missing");return;}SuiCommand::WidgetPropertyVector properties;subscription->getPropertySubscriptionsForEvent(properties);SuiEventNotification response(id,index,properties.size());
        for(size_t i=0;i<properties.size();++i){std::string const &prop=properties[i].propertyName;if(prop!="Text"&&prop!="LocalText"&&prop!="SelectedText"&&prop!="SelectedRow"&&prop!="SelectedIndex"){fail("unsupported SUI subscribed property");return;}response.addSubscribedProperty(Unicode::narrowToWide(text));}
        game->message(response);pages.erase(page);std::ostringstream detail;detail<<"\"subscription\":"<<index;event("sui_answered",detail.str());return;
    }
    fail("unknown or invalid action");
}
int runDriver() {
    Driver d;d.project=ConfigFile::getKeyString("ProtocolDriver64","project","");d.account=ConfigFile::getKeyString("ProtocolDriver64","account","");d.name=ConfigFile::getKeyString("ProtocolDriver64","character","");
    for(int index=0;index<=31;++index) {
        std::string id=ConfigFile::getKeyString("ProtocolDriver64","companion",index,"");
        std::string name=ConfigFile::getKeyString("ProtocolDriver64","companionName",index,"");
        if(id.empty() && name.empty()) break;
        if(!d.companions.add(id,name)) return 2;
    }
    std::string ship=ConfigFile::getKeyString("ProtocolDriver64","ship","");
    if(!ship.empty()){if(!number(ship)||ship[0]=='-')return 2;d.ship=NetworkId(ship);}
    int timeout=ConfigFile::getKeyInt("ProtocolDriver64","timeoutSeconds",300);d.creating=ConfigFile::getKeyBool("ProtocolDriver64","create",false);
    if(d.project.size()!=22||d.project.substr(0,14)!="swg-cold-test-"||d.project.substr(14).find_first_not_of("abcdef0123456789")!=std::string::npos || !identifier(d.account)||d.account.size()!=14||d.account.substr(0,7)!="capbot_"||d.account.substr(7).find_first_not_of("abcdef0123456789")!=std::string::npos||d.name.substr(0,3)!="Cap"||d.name.size()!=15||d.name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos||timeout<10||timeout>900){event("failure","\"reason\":\"invalid fixture identity or limits\"");return 2;}
    d.expires=seconds()+timeout;fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
    event("started","\"project\":"+quote(d.project)+",\"account\":"+quote(d.account));d.login=new Peer(d,true,"login",45053);
    while(!d.done){Clock::update();NetworkHandler::update();NetworkHandler::dispatch();d.tick();Os::sleep(10);}
    return d.failed?1:0;
}
// Offline wire check: print the bytes one client action would send, then exit. No config,
// no network. Usage: driver --encode <character> <sequence> <verb> [target] [name] [value...]
int encodeClientAction(int argc,char **argv) {
    if(argc<5||!number(argv[2])||argv[2][0]=='-'||!number(argv[3])||argv[3][0]=='-')return 2;
    ClientAction a;a.verb=argv[4];int next=5;
    if(next<argc && number(argv[next]) && argv[next][0]!='-'){a.target=NetworkId(std::string(argv[next]));++next;}
    if(a.verb=="tradeCredits"){if(!a.target.isValid())return 2;a.amount=static_cast<int>(std::atol(argv[5]));a.target=NetworkId::cms_invalid;}
    else if(next<argc){a.targetName=argv[next++];}
    for(;next<argc;++next){if(!a.text.empty())a.text+=' ';a.text+=argv[next];}
    Outgoing out;if(!buildClientAction(a,NetworkId(std::string(argv[2])),static_cast<uint32>(std::strtoul(argv[3],0,10)),out))return 1;
    Archive::ByteStream bytes;out.message->pack(bytes);std::string hex;char digits[3];
    for(unsigned int i=0;i<bytes.getSize();++i){std::sprintf(digits,"%02x",bytes.getBuffer()[i]);hex+=digits;}
    std::printf("ENCODED %s %s\n",a.verb.c_str(),hex.c_str());std::fflush(stdout);return 0;
}
void installControllerMessages() {
    ControllerMessageFactory::install();ObjControllerMessage::install();
    MessageQueueDataTransform::install();MessageQueueDataTransformWithParent::install();
    MessageQueueTeleportAck::install();MessageQueueObjectMenuRequest::install();MessageQueueCommandQueueEnqueue::install();
    MessageQueueStartNpcConversation::install();MessageQueueStringList::install();
    MessageQueueCommandQueueRemove::install();MessageQueueSecureTrade::install();
}
}
int main(int argc,char **argv) {
    if(sizeof(void*)!=8)return 2;
    bool const encode=argc>=2 && std::strcmp(argv[1],"--encode")==0;
    if(argc!=2 && !encode)return 2;
    SetupSharedThread::install();SetupSharedDebug::install(1024);SetupSharedFoundation::Data foundation(SetupSharedFoundation::Data::D_game);SetupSharedFoundation::install(foundation);
    if(encode){installControllerMessages();int result=encodeClientAction(argc,argv);SetupSharedFoundation::remove();SetupSharedThread::remove();return result;}
    if(!ConfigFile::loadFile(argv[1]))return 2;
    SetupSharedFile::install(false);SetupSharedRandom::install(1);SetupSharedNetwork::SetupData network;SetupSharedNetwork::getDefaultClientSetupData(network);SetupSharedNetwork::install(network);
    installControllerMessages();
    int result=runDriver();SetupSharedFoundation::remove();SetupSharedThread::remove();return result;
}
