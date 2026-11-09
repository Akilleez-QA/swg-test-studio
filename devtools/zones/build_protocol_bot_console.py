#!/usr/bin/env python3
"""Build the fixture bot's typed setup/inspection console; no arbitrary scripts."""
from pathlib import Path
import re
import tempfile
from test_login_recovery import main, REPO

if __name__ == '__main__':
    source = Path(__file__).with_name('capacity_console.cpp').read_text()
    commands = '''
    std::string heroicMethod;
    if(command=="botHeroicInspect")heroicMethod="inspectHeroic";
    if(command=="botHeroicEnter")heroicMethod="enter";
    if(command=="botHeroicCapture")heroicMethod="capture";
    if(command=="botHeroicExitSetup")heroicMethod="exitSetup";
    if(command=="botHeroicFinish")heroicMethod="finish";
    if(command=="botHeroicAnchorLeft")heroicMethod="anchorLeft";
    if(command=="botHeroicAnchorRight")heroicMethod="anchorRight";
    if(command=="botHeroicClose")heroicMethod="close";
    if(command=="botHeroicHome")heroicMethod="home";
    if(command.size()==17 && command.substr(0,16)=="botHeroicPrepare" && command[16]>='0' && command[16]<='5')
        heroicMethod="prepare"+command.substr(16);
    if(argc==7 && !heroicMethod.empty() && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.heroic_entry "+heroicMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    std::string crewMethod;
    if(command=="botCrewShipPrepare")crewMethod="prepare";
    if(command=="botCrewShipInspect")crewMethod="inspect";
    if(command=="botCrewShipRemove")crewMethod="remove";
    if(argc==7 && !crewMethod.empty() && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.private_ship_crew "+crewMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    std::string encounterMethod;
    if(command=="botEncounterLoadSpawn")encounterMethod="encounterLoadSpawn";
    if(command=="botEncounterLoadUnload")encounterMethod="encounterLoadUnload";
    if(command=="botEncounterLoadInspect")encounterMethod="encounterLoadInspect";
    if(command=="botEncounterReleaseInspect")encounterMethod="encounterReleaseInspect";
    if(command=="botEncounterReleaseSpawn")encounterMethod="encounterReleaseSpawn";
    if(command=="botEncounterReleaseRemove")encounterMethod="encounterReleaseRemove";
    if(argc==7 && !encounterMethod.empty() && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.protocol_bot "+encounterMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    if(command=="botEncounterReleaseGive" && argc==10 && number(argv[3]) && number(argv[4]) && number(argv[5]) && number(argv[7]) && number(argv[8]) &&
        argv[3][0]!='0' && argv[4][0]!='0' && argv[5][0]!='0' && argv[7][0]!='0' && argv[8][0]!='0') {
        std::string actor=argv[6],holder=argv[9];
        if(actor.size()!=15 || holder.size()!=15 || actor.substr(0,3)!="Cap" || holder.substr(0,3)!="Cap" ||
            actor.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos ||
            holder.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.protocol_bot encounterReleaseGive "+argv[4]+":"+argv[5]+":"+actor+","+argv[7]+":"+argv[8]+":"+holder;
        argc=3;valid=true;
    }
    std::string groundMethod;
    if(command=="botGroundCellApproach")groundMethod="approach";
    if(command=="botGroundCellEnter")groundMethod="enter";
    if(command=="botGroundCellInspect")groundMethod="inspectCell";
    if(argc==7 && !groundMethod.empty() && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.ground_cell_entry "+groundMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    std::string publicMethod;
    if(command=="botPublicEnter0")publicMethod="enter0";
    if(command=="botPublicEnter1")publicMethod="enter1";
    if(command=="botPublicExitMyyydril")publicMethod="exitMyyydril";
    if(command=="botPublicExitNova")publicMethod="exitNova";
    if(argc==7 && !publicMethod.empty() && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.hosted_public_entry "+publicMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    bool worldCommand=command=="botWorldHome" || command=="botWorldClear";
    std::string worldMethod=command=="botWorldHome"?"worldHome":"worldClear";
    if(command.size()>=14 && command.size()<=15 && command.substr(0,13)=="botWorldEnter") {
        std::string suffix=command.substr(13);
        bool digits=suffix.find_first_not_of("0123456789")==std::string::npos;
        int index=digits?suffix[0]-'0':-1;
        if(digits && suffix.size()==2)index=index*10+suffix[1]-'0';
        worldCommand=digits && index>=0 && index<18 && (suffix.size()==1 || suffix[0]!='0');
        worldMethod="worldEnter"+suffix;
    }
    if(argc==7 && worldCommand && number(argv[3]) && number(argv[4]) && number(argv[5])) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        command="game "+std::string(argv[3])+" runScript fixture.world_entry "+worldMethod+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
    if(argc==4 && number(argv[3]) && command=="botReload") {
        command="game "+std::string(argv[3])+" reloadScript fixture.protocol_bot";
        argc=3;valid=true;
    }
    if(argc==7 && number(argv[3]) && number(argv[4]) && number(argv[5]) &&
       (command=="botOriginProbe" || command=="botPrivateMtpPrepare" || command=="botPrivateMtpEnter" || command=="botPrivateMtpInspect" || command=="botPrivateMtpClose" || command=="botPrivateMtpLeave" || command=="botPrivateMtpHome" || command=="botHostedSelection" || command=="botPrivateSoloEligibility" || command=="botPrivateSoloMtp" || command=="botPrivateSoloObiwan" || command=="botFalconEnter" || command=="botFalconInspect" || command=="botFalconArm" || command=="botFalconExit" || command=="botWorldSaveStamp" || command=="botWorldSaveClear" || command=="botInspect" || command=="botStation" || command=="botTerminals" || command=="botPrepare" || command=="botPilotSetup" || command=="botLandingSetup" || command=="botSplitStation" || command=="botFriendSetup" || command=="botKashyyykSetup" || command=="botRryattSetup" || command=="botRryattExitSetup" || command=="botKashyyykHome" || command=="botRryattDiagnostics" || command=="botRryattAudit" || command=="botRryattCombatSetup" || command=="botRryattEnemySetup" || command=="botRryattEnemyCleanup" || command=="botRryattQuestReset" || command=="botRryattMaster" || command=="botRryattDeath" || command=="botRryattResurrect" || command=="botRryattLegacy" || command=="botRryattStale" || command=="botRryattForeignGuide" || (command.size()==15 && command.substr(0,14)=="botRryattGuide" && command[14]>='0' && command[14]<='7'))) {
        std::string name=argv[6];
        if(name.size()!=15 || name.substr(0,3)!="Cap" || name.substr(3).find_first_not_of("abcdefghijklmnopqrstuvwxyz")!=std::string::npos)return 2;
        std::string method=command=="botOriginProbe" ? "originProbe" : command=="botPrivateMtpPrepare" ? "privateMtpPrepare" : command=="botPrivateMtpEnter" ? "privateMtpEnter" : command=="botPrivateMtpInspect" ? "privateMtpInspect" : command=="botPrivateMtpClose" ? "privateMtpClose" : command=="botPrivateMtpLeave" ? "privateMtpLeave" : command=="botPrivateMtpHome" ? "privateMtpHome" : command=="botHostedSelection" ? "hostedSelection" : command=="botPrivateSoloEligibility" ? "privateSoloEligibility" : command=="botPrivateSoloMtp" ? "privateSoloMtp" : command=="botPrivateSoloObiwan" ? "privateSoloObiwan" : command=="botFalconEnter" ? "falconEnter" : command=="botFalconInspect" ? "falconInspect" : command=="botFalconArm" ? "falconArm" : command=="botFalconExit" ? "falconExit" : command=="botWorldSaveStamp" ? "worldSaveStamp" : command=="botWorldSaveClear" ? "worldSaveClear" : command=="botInspect" ? "inspect" : command=="botStation" ? "station" : command=="botTerminals" ? "terminals" : command=="botPrepare" ? "prepare" : command=="botPilotSetup" ? "pilotSetup" : command=="botLandingSetup" ? "landingSetup" : command=="botSplitStation" ? "splitStation" : command=="botKashyyykSetup" ? "kashyyykSetup" : command=="botRryattSetup" ? "rryattSetup" : command=="botRryattExitSetup" ? "rryattExitSetup" : command=="botKashyyykHome" ? "kashyyykHome" : command=="botRryattDiagnostics" ? "rryattDiagnostics" : command=="botRryattAudit" ? "rryattAudit" : command=="botRryattCombatSetup" ? "rryattCombatSetup" : command=="botRryattEnemySetup" ? "rryattEnemySetup" : command=="botRryattEnemyCleanup" ? "rryattEnemyCleanup" : command=="botRryattQuestReset" ? "rryattQuestReset" : command=="botRryattMaster" ? "rryattMaster" : command=="botRryattDeath" ? "rryattDeath" : command=="botRryattResurrect" ? "rryattResurrect" : command=="botRryattLegacy" ? "rryattLegacy" : command=="botRryattStale" ? "rryattStale" : command=="botRryattForeignGuide" ? "rryattForeignGuide" : command.substr(0,14)=="botRryattGuide" ? "rryattGuide"+command.substr(14) : "friendSetup";
        command="game "+std::string(argv[3])+" runScript fixture.protocol_bot "+method+" "+argv[4]+":"+argv[5]+":"+name;
        argc=3;valid=true;
    }
'''
    source, count = re.subn(r'#ifdef SWG_FALCON_FIXTURE.*?#endif', commands, source, flags=re.S)
    if count != 1:
        raise RuntimeError('Expected one fixture command block')
    shared = REPO / 'src/engine/shared/library'
    roots = [shared / name / 'include/public' for name in ('sharedFoundation', 'sharedFoundationTypes',
        'sharedMemoryManager', 'sharedDebug', 'sharedNetworkMessages', 'sharedMessageDispatch',
        'sharedMath', 'sharedSynchronization', 'sharedThread')]
    roots += [REPO / 'src/external/ours/library' / name / 'include' for name in ('archive', 'unicode')]
    with tempfile.TemporaryDirectory(prefix='swg-bot-console-') as folder:
        path = Path(folder) / 'console.cpp'
        path.write_text(source)
        main(source=path, label='fixture bot console', include_roots=roots, native_required=True, gnu_cpp03=True)
