package script.fixture;
import script.*;
import script.library.*;

/** Dedicated protocol bots in labelled copied schemas only; never a role image. */
public class protocol_bot extends base_script {
    protected String[] identity(String value, String method) throws InterruptedException {
        value=value.trim();
        if(value.startsWith(method+" ")) value=value.substring(method.length()+1);
        String schema=getConfigSetting("dbProcess","schemaOwner");
        if(!"1".equals(getConfigSetting("GameServer","clientIsolationFixture")) ||
                schema==null || !schema.matches("WGC_[A-F0-9]{12}")) return null;
        String[] fields=value.split(":",-1);
        if(fields.length!=3 || !fields[0].matches("[1-9][0-9]{0,18}") ||
                !fields[1].matches("[1-9][0-9]{0,9}") || !fields[2].matches("Cap[a-z]{12}")) return null;
        return fields;
    }
    protected obj_id player(String[] fields) throws InterruptedException {
        if(fields==null) return null;
        obj_id p=obj_id.getObjId(Long.parseLong(fields[0]));
        if(!isIdValid(p) || !p.isAuthoritative() || !isPlayer(p)) return null;
        if(!fields[2].equals(getPlayerFullName(p)) ||
                Integer.toUnsignedLong(getPlayerStationId(p))!=Long.parseLong(fields[1]) || isGod(p)) return null;
        return p;
    }
    public String inspect(String value) throws InterruptedException {
        String[] fields=identity(value,"inspect");
        if(fields==null) return "protocol_bot=invalid-scope";
        obj_id p=player(fields);
        if(!isIdValid(p)) {
            obj_id candidate=obj_id.getObjId(Long.parseLong(fields[0]));
            return isIdValid(candidate) && candidate.isAuthoritative() ? "protocol_bot=invalid-identity" : "protocol_bot=absent";
        }
        location l=getLocation(p);
        obj_id g=getGroupObject(p), ship=space_transition.getContainingShip(p);
        location s=isIdValid(ship)?getLocation(ship):null;
        obj_id root=getTopMostContainer(p);
        obj_id[] nearby=isIdValid(root)?getPlayerCreaturesInRange(getLocation(root),500.0f):null;
        boolean scanned=false;
        if(nearby!=null) for(obj_id candidate:nearby) if(p.equals(candidate)) scanned=true;
        dictionary friends=utils.getDictionaryScriptVar(p,"npe_instance_transfer_terminal.players");
        String[] subset=utils.getStringArrayScriptVar(p,"npe_instance_transfer_terminal.players_subset");
        String names="";
        if(friends!=null) for(java.util.Enumeration keys=friends.keys();keys.hasMoreElements();) {
            String key=String.valueOf(keys.nextElement());
            if(key.matches("Cap[a-z]{12}")) names+=(names.length()==0?"":",")+key;
        }
        obj_id weapon=getCurrentWeapon(p);
        obj_id enemy=utils.getObjIdScriptVar(p,"fixture.rryatt.enemy");
        boolean validEnemy=isIdValid(enemy) && exists(enemy) && p.equals(getObjIdObjVar(enemy,"fixture.rryatt.owner"));
        if(!validEnemy && "kashyyyk_rryatt_trail".equals(getCurrentSceneName()) && isIdValid(g)) {
            obj_id[] candidates=getCreaturesInRange(l,8.0f);
            if(candidates!=null && candidates.length<=64) for(obj_id candidate:candidates) {
                obj_id owner=getObjIdObjVar(candidate,"fixture.rryatt.owner");
                if(!isPlayer(candidate) && isIdValid(owner) && isPlayer(owner) &&
                   getPlayerFullName(owner).matches("Cap[a-z]{12}") && g.equals(getGroupObject(owner)) &&
                   getZoneInstanceId(candidate)==getZoneInstanceId(p)) {enemy=candidate;validEnemy=true;break;}
            }
        }

        int ownedEnemies=0;
        if("kashyyyk_rryatt_trail".equals(getCurrentSceneName()) && getCurrentZoneInstanceId()>=0) {
            obj_id[] owned=getAllObjectsWithScript(l,16000.0f,"fixture.protocol_bot");
            if(owned!=null) for(obj_id candidate:owned)
                if(!isPlayer(candidate) && p.equals(getObjIdObjVar(candidate,"fixture.rryatt.owner"))) ownedEnemies++;
        }
        location[] clonePoints=utils.getLocationArrayScriptVar(p,pclib.VAR_REVIVE_SPAWN);
        String cloneTargets="";
        if(clonePoints!=null && clonePoints.length<=96) for(int i=0;i<clonePoints.length;i++) {
            location q=clonePoints[i];
            cloneTargets+=(i==0?"":",")+(q==null?"none":q.area+":"+q.x+":"+q.y+":"+q.z+":"+locations.getBuildoutAreaRow(q));
        }
        obj_id lastKiller=utils.getObjIdScriptVar(p,"lastKiller");
        location worldPoint=getWorldLocation(p);
        return "protocol_bot=present player="+p+" connected="+isPlayerConnected(p)+
                " scene="+l.area+" instance="+getZoneInstanceId(p)+" cell="+l.cell+
                " building="+getTopMostContainer(p)+" room="+getCellName(l.cell)+
                " x="+l.x+" y="+l.y+" z="+l.z+" weapon_type="+(isIdValid(weapon)?getWeaponType(weapon):-1)+" posture="+getPosture(p)+" combat="+getState(p,STATE_COMBAT)+
                " buildout_row="+locations.getBuildoutAreaRow(p)+
                " instance_controller="+getObjIdObjVar(p,space_dungeon.INSTANCE_ID)+
                " last_rryatt_guide="+getObjIdObjVar(p,"lastRryattTransition")+
                " fixture_version=stage6-public-group-v1"+
                " world_action="+utils.getStringScriptVar(p,"fixture.world.result")+
                " public_action="+utils.getStringScriptVar(p,"fixture.public.result")+
                " fixture_attached="+hasScript(p,"fixture.protocol_bot")+
                " fixture_setup_serial="+utils.getIntScriptVar(p,"fixture.completed.serial")+
                " fixture_setup_action="+utils.getStringScriptVar(p,"fixture.completed.action")+
                " fixture_setup_accepted="+utils.getStringScriptVar(p,"fixture.completed.accepted")+
                " dead="+isDead(p)+
                " health="+getAttrib(p,HEALTH)+" max_health="+getMaxAttrib(p,HEALTH)+
                " last_killer="+lastKiller+
                " last_killer_template="+(isIdValid(lastKiller) && exists(lastKiller)?getTemplateName(lastKiller):"unloaded")+
                " world_x="+(worldPoint==null?Float.NaN:worldPoint.x)+
                " world_y="+(worldPoint==null?Float.NaN:worldPoint.y)+
                " world_z="+(worldPoint==null?Float.NaN:worldPoint.z)+
                " mastery="+groundquests.hasCompletedQuest(p,"ep3_rryatt_trail_mastery")+
                " mastery_active="+groundquests.isQuestActive(p,"ep3_rryatt_trail_mastery")+
                " clone_page="+utils.getIntScriptVar(p,pclib.VAR_SUI_CLONE)+
                " clone_targets="+(cloneTargets.length()==0?"none":cloneTargets)+
                " clone_mapping_sources="+cloneMappingSources(p)+
                " on_floor="+isOnAFloor(p)+
                " standing_floor_y="+(isOnAFloor(p)?getFloorHeightAtRelativePointOnSameFloorAsObject(p,0,0):Float.NaN)+
                " terrain_y="+(!isIdValid(l.cell) && (l.area.startsWith("kashyyyk_") || getZoneInstanceId(p)==0 &&
                    ("lok".equals(l.area)||"dathomir".equals(l.area)||"yavin4".equals(l.area)||"corellia".equals(l.area)))?
                    getHeightAtLocation(l.x,l.z):Float.NaN)+
                " guide_visible="+(isIdValid(utils.getObjIdScriptVar(p,"fixture.rryatt.guide")) && exists(utils.getObjIdScriptVar(p,"fixture.rryatt.guide")) && canSee(p,utils.getObjIdScriptVar(p,"fixture.rryatt.guide")))+
                " rryatt_script="+hasScript(p,"systems.movement.public_instance_travel")+
                " rryatt_request="+utils.getIntScriptVar(p,"rryatt.entry.request")+
                " rryatt_choices="+utils.getIntScriptVar(p,"rryatt.entry.count")+
                " rryatt_registry_count="+utils.getIntScriptVar(p,"fixture.rryatt.count")+
                " rryatt_registry="+utils.getStringScriptVar(p,"fixture.rryatt.summary")+
                " rryatt_permission="+transition.hasPermissionForZone(p,"kachirho_rryatt","initialRequiredFlag")+
                " rryatt_flag="+dataTableGetString("datatables/travel/zone_transition.iff","kachirho_rryatt","initialRequiredFlag")+
                " rryatt_gate_visible="+(isIdValid(utils.getObjIdScriptVar(p,"fixture.rryatt.gate")) && exists(utils.getObjIdScriptVar(p,"fixture.rryatt.gate")) && canSee(p,utils.getObjIdScriptVar(p,"fixture.rryatt.gate")))+
                " family="+fixtureFamily(p)+" gamma_dialog_pending="+utils.hasScriptVar(p,"npe.gamma_travel.pid")+
                " journal="+hasScript(p,"npe.trigger_journal")+" invulnerable="+isInvulnerable(p)+
                " gamma_pending="+utils.hasScriptVar(p,"npe.gamma_travel.pid")+
                " pending="+hasObjVar(p,"capacity.groupTransfer.id")+
                " grant="+getStringObjVar(p,"capacity.groupTransfer.id")+
                " stage="+getStringObjVar(p,"capacity.groupTransfer.stage")+
                " owned_enemy_count="+ownedEnemies+" enemy_serial="+utils.getIntScriptVar(p,"fixture.rryatt.enemy.serial")+
                " enemy_pending="+utils.hasScriptVar(p,"fixture.rryatt.enemy.pending")+
                " enemy="+(validEnemy?enemy:null)+" enemy_health="+(validEnemy?getAttrib(enemy,HEALTH):-1)+
                " can_attack="+(validEnemy && pvpCanAttack(p,enemy))+" can_be_attacked="+(validEnemy && pvpCanAttack(enemy,p))+
                " enemy_distance="+(validEnemy?getDistance(p,enemy):-1)+
                " protected="+hasObjVar(p,"capacity.transferProtection.operation")+
                " outstanding="+hasObjVar(p,"hasOutstandingRequestSceneTransfer")+
                " friend_count="+(friends==null?-1:friends.size())+
                " friend_names="+(names.length()==0?"none":names)+
                " friend_subset="+(subset==null?-1:subset.length)+
                " station_scan="+scanned+" station_scan_count="+(nearby==null?-1:nearby.length)+
                " group="+g+" leader="+(isIdValid(g)?getGroupLeaderId(g):null)+
                " members="+(isIdValid(g)?getGroupMemberIds(g).length:0)+
                " ship="+ship+" owner="+(isIdValid(ship)?getOwner(ship):null)+
                " pilot="+(isIdValid(ship)?getPilotId(ship):null)+
                " ship_instance="+(isIdValid(ship)?getZoneInstanceId(ship):-1)+
                " ship_x="+(s!=null?s.x:0)+" ship_y="+(s!=null?s.y:0)+" ship_z="+(s!=null?s.z:0)+publicPortalPose(p,l);
    }
    public String originProbe(String value) throws InterruptedException {
        obj_id p=player(identity(value,"originProbe"));
        if(!hostedActor(p))return "protocol_bot=invalid-origin-scope";
        String previous=utils.getStringScriptVar(p,"fixture.origin.result");
        if(previous!=null)return previous;
        if(!utils.hasScriptVar(p,"fixture.origin.pending")) {
            dictionary request=new dictionary();request.put("identity",value);
            utils.setScriptVar(p,"fixture.origin.pending",true);
            if(!messageTo(p,"fixtureOriginProbe",request,0.1f,false)) {
                utils.removeScriptVar(p,"fixture.origin.pending");return "protocol_bot=invalid-origin-schedule";
            }
        }
        return "protocol_bot=origin pending=true";
    }
    public int fixtureOriginProbe(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=request==null?null:player(identity(request.getString("identity"),"originProbe"));
        if(!hostedActor(p) || !self.equals(p) || !utils.hasScriptVar(p,"fixture.origin.pending"))return SCRIPT_CONTINUE;
        if(utils.hasScriptVar(p,"fixture.origin.started"))return SCRIPT_CONTINUE;
        utils.setScriptVar(p,"fixture.origin.started",true);
        utils.setScriptVar(p,"fixture.origin.result","protocol_bot=origin pending=false accepted=false unfinished=true");
        utils.removeScriptVar(p,"fixture.origin.pending");
        String state=fixtureEncounterOrigin(null);
        if(state==null || state.indexOf("origin_intact=true")<0) {
            utils.setScriptVar(p,"fixture.origin.result","protocol_bot=origin pending=false accepted=false observer=false "+
                (state==null?"origin_null=true":state));return SCRIPT_CONTINUE;
        }
        obj_id enemy=null;boolean removed=false;
        try {
            // One original weak droid, removed in this same game event before
            // an AI frame. Never change an existing NPC or player combat state.
            enemy=create.object("npe_droid_4warning_weak",getLocation(p),2);
            String before=isIdValid(enemy)?fixtureEncounterOrigin(enemy):null;
            removed=isIdValid(enemy) && destroyObject(enemy);
            // destroyObject invalidates the Java handle. Its immutable native
            // ID still addresses the retained receipt; it need not be live.
            String after=enemy!=null?fixtureEncounterOrigin(enemy):null;
            boolean captured=before!=null && before.indexOf("origin_initialized=true")>=0 &&
                before.indexOf("origin_destroyed=false")>=0;
            boolean destroyed=after!=null && after.indexOf("origin_destroyed=true")>=0;
            utils.setScriptVar(p,"fixture.origin.result","protocol_bot=origin pending=false accepted="+
                (removed && captured && destroyed)+" captured="+captured+" removed="+removed+
                " "+(after==null?"origin_missing=true":after));
        } finally {
            if(!removed && isIdValid(enemy) && exists(enemy) && !isPlayer(enemy)) {
                removed=destroyObject(enemy);
                if(!removed)utils.setScriptVar(p,"fixture.origin.result","protocol_bot=origin pending=false accepted=false cleanup_failed=true object="+enemy);
            }
        }
        return SCRIPT_CONTINUE;
    }
    public String encounterLoadSpawn(String value) throws InterruptedException {return encounterLoadRequest(value,"encounterLoadSpawn","spawn");}
    public String encounterLoadUnload(String value) throws InterruptedException {return encounterLoadRequest(value,"encounterLoadUnload","unload");}
    public String encounterLoadInspect(String value) throws InterruptedException {return encounterLoadRequest(value,"encounterLoadInspect","inspect");}
    public String encounterReleaseSpawn(String value) throws InterruptedException {return encounterLoadRequest(value,"encounterReleaseSpawn","releaseSpawn");}
    private String encounterLoadRequest(String value,String method,String action) throws InterruptedException {
        obj_id p=privateMtpPlayer(value,method),root=privateMtpRoot(p);
        if(!privateMtpQuiet(p) || !isIdValid(root) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1)
            return "protocol_bot=encounter-load pending=false accepted=false phase="+action;
        int session=instance.getPrivateInstanceSession(root);
        obj_id original=utils.getObjIdScriptVar(p,"fixture.encounterLoad.root");
        if(original!=null && (!original.equals(root) || utils.getIntScriptVar(p,"fixture.encounterLoad.session")!=session))
            return "protocol_bot=encounter-load pending=false accepted=false phase="+action+" changed_session=true";
        String key="fixture.encounterLoad."+action;
        String result=utils.getStringScriptVar(p,key+".result");
        if(result!=null) {
            if("inspect".equals(action) && result.indexOf("present=true")>=0)utils.removeScriptVar(p,key+".result");
            return result;
        }
        if(!utils.hasScriptVar(p,key+".pending")) {
            int serial=utils.getIntScriptVar(p,key+".serial");
            if(serial<0 || serial==Integer.MAX_VALUE)return "protocol_bot=encounter-load pending=false accepted=false phase="+action;
            dictionary request=new dictionary();request.put("identity",value);request.put("method",method);request.put("action",action);
            request.put("root",root);request.put("session",session);request.put("serial",serial+1);
            utils.setScriptVar(p,"fixture.encounterLoad.root",root);utils.setScriptVar(p,"fixture.encounterLoad.session",session);
            utils.setScriptVar(p,key+".serial",serial+1);utils.setScriptVar(p,key+".pending",true);
            if(!messageTo(p,"fixtureEncounterLoadProbe",request,0.1f,false)) {
                utils.removeScriptVar(p,key+".pending");return "protocol_bot=encounter-load pending=false accepted=false phase="+action;
            }
        }
        return "protocol_bot=encounter-load pending=true phase="+action;
    }
    public int fixtureEncounterLoadProbe(obj_id self,dictionary request) throws InterruptedException {
        if(request==null)return SCRIPT_CONTINUE;
        String method=request.getString("method"),action=request.getString("action");
        if(!("spawn".equals(action) && "encounterLoadSpawn".equals(method)) &&
           !("releaseSpawn".equals(action) && "encounterReleaseSpawn".equals(method)) &&
           !("unload".equals(action) && "encounterLoadUnload".equals(method)) &&
           !("inspect".equals(action) && "encounterLoadInspect".equals(method)))return SCRIPT_CONTINUE;
        obj_id p=privateMtpPlayer(request.getString("identity"),method),root=privateMtpRoot(p);
        String key="fixture.encounterLoad."+action;
        if(!isIdValid(p) || !self.equals(p) || !utils.hasScriptVar(p,key+".pending") ||
            request.getInt("serial")!=utils.getIntScriptVar(p,key+".serial"))return SCRIPT_CONTINUE;
        utils.removeScriptVar(p,key+".pending");
        utils.setScriptVar(p,key+".result","protocol_bot=encounter-load pending=false accepted=false phase="+action);
        if(!privateMtpQuiet(p) || !isIdValid(root) || !root.equals(request.getObjId("root")) ||
            instance.getPrivateInstanceSession(root)!=request.getInt("session"))return SCRIPT_CONTINUE;
        obj_id target=utils.getObjIdScriptVar(p,"fixture.encounterLoad.object");boolean accepted=false;
        if("spawn".equals(action) || "releaseSpawn".equals(action)) {
            if(target!=null)return SCRIPT_CONTINUE;
            location point=getLocation(p);if(point==null || !isIdValid(point.cell))return SCRIPT_CONTINUE;
            target=createObject("releaseSpawn".equals(action)?"object/tangible/loot/misc/recording_rod_s01.iff":"object/tangible/container/drum/tatt_drum_1.iff",point);
            if(!isIdValid(target))return SCRIPT_CONTINUE;
            utils.setScriptVar(p,"fixture.encounterLoad.object",target);
            String ownership=getStringObjVar(target,"__server_encounter_v1");
            accepted=ownership!=null && ownership.length()>0 && persistObject(target);
            if(!accepted){destroyObject(target);return SCRIPT_CONTINUE;}
        } else {
            if(target==null)return SCRIPT_CONTINUE;
            accepted="inspect".equals(action) || fixtureUnloadEncounterObject(target);
        }
        String origin=fixtureEncounterOrigin(target);
        if(origin==null || origin.indexOf("origin_intact=true")<0)return SCRIPT_CONTINUE;
        boolean present=origin.indexOf("origin_present=true")>=0;
        utils.setScriptVar(p,key+".result","protocol_bot=encounter-load pending=false accepted="+accepted+" phase="+action+
            " object="+target+" root="+root+" session="+request.getInt("session")+" present="+present+" "+origin);
        return SCRIPT_CONTINUE;
    }
    public String encounterReleaseGive(String value) throws InterruptedException {
        String[] pair=value.trim().split(",",-1);
        if(pair.length!=2)return "protocol_bot=encounter-release pending=false accepted=false";
        obj_id p=privateMtpPlayer(pair[0],"encounterReleaseGive"),holder=player(identity(pair[1],"encounterReleaseGive"));
        obj_id root=privateMtpRoot(p),target=utils.getObjIdScriptVar(p,"fixture.encounterLoad.object");
        if(!privateMtpQuiet(p) || !isIdValid(root) || !root.equals(utils.getObjIdScriptVar(p,"fixture.encounterLoad.root")) ||
            instance.getPrivateInstanceSession(root)!=utils.getIntScriptVar(p,"fixture.encounterLoad.session") ||
            !isIdValid(holder) || p.equals(holder) || !isPlayerConnected(holder) ||
            !hasScript(holder,"fixture.protocol_bot") || isIdValid(getGroupObject(holder)) || getState(holder,STATE_COMBAT)!=0 ||
            getZoneInstanceId(holder)!=getZoneInstanceId(p) || !isIdValid(target))
            return "protocol_bot=encounter-release pending=false accepted=false";
        obj_id previous=utils.getObjIdScriptVar(p,"fixture.encounterRelease.holder");
        if(previous!=null && !previous.equals(holder))return "protocol_bot=encounter-release pending=false accepted=false changed_holder=true";
        String result=utils.getStringScriptVar(p,"fixture.encounterRelease.result");if(result!=null)return result;
        if(!utils.hasScriptVar(p,"fixture.encounterRelease.pending")) {
            dictionary request=new dictionary();request.put("identity",value);request.put("object",target);request.put("root",root);
            request.put("session",instance.getPrivateInstanceSession(root));
            utils.setScriptVar(p,"fixture.encounterRelease.holder",holder);utils.setScriptVar(p,"fixture.encounterRelease.pending",true);
            if(!messageTo(p,"fixtureEncounterReleaseGive",request,0.1f,false)) {
                utils.removeScriptVar(p,"fixture.encounterRelease.pending");
                utils.setScriptVar(p,"fixture.encounterRelease.result","protocol_bot=encounter-release pending=false accepted=false enqueue=false");
            }
        }
        return "protocol_bot=encounter-release pending=true";
    }
    public int fixtureEncounterReleaseGive(obj_id self,dictionary request) throws InterruptedException {
        if(request==null)return SCRIPT_CONTINUE;
        String[] pair=request.getString("identity").trim().split(",",-1);if(pair.length!=2)return SCRIPT_CONTINUE;
        obj_id p=privateMtpPlayer(pair[0],"encounterReleaseGive"),holder=player(identity(pair[1],"encounterReleaseGive"));
        if(!isIdValid(p) || !self.equals(p) || !utils.hasScriptVar(p,"fixture.encounterRelease.pending"))return SCRIPT_CONTINUE;
        utils.removeScriptVar(p,"fixture.encounterRelease.pending");
        utils.setScriptVar(p,"fixture.encounterRelease.result","protocol_bot=encounter-release pending=false accepted=false");
        obj_id root=privateMtpRoot(p),target=utils.getObjIdScriptVar(p,"fixture.encounterLoad.object");
        if(!privateMtpQuiet(p) || !isIdValid(root) || !root.equals(utils.getObjIdScriptVar(p,"fixture.encounterLoad.root")) ||
            instance.getPrivateInstanceSession(root)!=utils.getIntScriptVar(p,"fixture.encounterLoad.session") || !root.equals(request.getObjId("root")) ||
            instance.getPrivateInstanceSession(root)!=request.getInt("session") || !isIdValid(target) || !target.equals(request.getObjId("object")) ||
            !isIdValid(holder) || p.equals(holder) || !holder.equals(utils.getObjIdScriptVar(p,"fixture.encounterRelease.holder")) ||
            !isPlayerConnected(holder) || !hasScript(holder,"fixture.protocol_bot") || isIdValid(getGroupObject(holder)) || getState(holder,STATE_COMBAT)!=0 ||
            getZoneInstanceId(holder)!=getZoneInstanceId(p) || !root.equals(getTopMostContainer(target)) ||
            !"object/tangible/loot/misc/recording_rod_s01.iff".equals(getTemplateName(target)) || !hasObjVar(target,"__server_encounter_v1"))return SCRIPT_CONTINUE;
        obj_id inventory=utils.getInventoryContainer(holder);
        if(!isIdValid(inventory) || hasObjVar(holder,"fixture.encounterRelease.object"))return SCRIPT_CONTINUE;
        // Move only this newly created probe through the original containment
        // API. Native ownership hooks supply its release record and load_with.
        setObjVar(target,"fixture.encounterRelease.creator",p);
        boolean transferred=putIn(target,inventory,p);
        boolean accepted=transferred && inventory.equals(getContainedBy(target)) && holder.equals(getContainedBy(inventory));
        if(accepted)setObjVar(holder,"fixture.encounterRelease.object",target);
        utils.setScriptVar(p,"fixture.encounterRelease.result","protocol_bot=encounter-release pending=false accepted="+accepted+
            " object="+target+" holder="+holder+" inventory="+inventory+" transferred="+transferred+" top="+getTopMostContainer(target)+" root="+root+" session="+request.getInt("session"));
        return SCRIPT_CONTINUE;
    }
    private boolean encounterReleaseHeld(obj_id p,obj_id target) throws InterruptedException {
        obj_id inventory=utils.getInventoryContainer(p);
        return isIdValid(target) && isIdValid(inventory) && inventory.equals(getContainedBy(target)) && p.equals(getContainedBy(inventory));
    }
    public String encounterReleaseInspect(String value) throws InterruptedException {
        obj_id p=player(identity(value,"encounterReleaseInspect"));
        if(!isIdValid(p) || !isPlayerConnected(p) || !hasScript(p,"fixture.protocol_bot"))return "protocol_bot=invalid-release-inspect";
        obj_id target=getObjIdObjVar(p,"fixture.encounterRelease.object");
        boolean present=isIdValid(target) && exists(target);
        return "protocol_bot=encounter-possession object="+target+" present="+present+" held="+
            (present && encounterReleaseHeld(p,target))+" creator="+(present?getObjIdObjVar(target,"fixture.encounterRelease.creator"):null);
    }
    public String encounterReleaseRemove(String value) throws InterruptedException {
        obj_id p=player(identity(value,"encounterReleaseRemove"));
        if(!isIdValid(p) || !isPlayerConnected(p) || !hasScript(p,"fixture.protocol_bot"))return "protocol_bot=invalid-release-remove";
        String result=utils.getStringScriptVar(p,"fixture.encounterRelease.remove.result");if(result!=null)return result;
        if(!utils.hasScriptVar(p,"fixture.encounterRelease.remove.pending")) {
            dictionary request=new dictionary();request.put("identity",value);request.put("object",getObjIdObjVar(p,"fixture.encounterRelease.object"));
            utils.setScriptVar(p,"fixture.encounterRelease.remove.pending",true);
            if(!messageTo(p,"fixtureEncounterReleaseRemove",request,0.1f,false)) {
                utils.removeScriptVar(p,"fixture.encounterRelease.remove.pending");
                utils.setScriptVar(p,"fixture.encounterRelease.remove.result","protocol_bot=release-remove pending=false accepted=false enqueue=false");
            }
        }
        return "protocol_bot=release-remove pending=true";
    }
    public int fixtureEncounterReleaseRemove(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=request==null?null:player(identity(request.getString("identity"),"encounterReleaseRemove"));
        if(!isIdValid(p) || !self.equals(p) || !utils.hasScriptVar(p,"fixture.encounterRelease.remove.pending"))return SCRIPT_CONTINUE;
        utils.removeScriptVar(p,"fixture.encounterRelease.remove.pending");
        utils.setScriptVar(p,"fixture.encounterRelease.remove.result","protocol_bot=release-remove pending=false accepted=false");
        obj_id target=getObjIdObjVar(p,"fixture.encounterRelease.object");
        if(!isIdValid(target) || !target.equals(request.getObjId("object")) || !encounterReleaseHeld(p,target) || isPlayer(target) ||
            !hasObjVar(target,"fixture.encounterRelease.creator") || !"object/tangible/loot/misc/recording_rod_s01.iff".equals(getTemplateName(target)))return SCRIPT_CONTINUE;
        boolean accepted=destroyObject(target);if(accepted)removeObjVar(p,"fixture.encounterRelease.object");
        utils.setScriptVar(p,"fixture.encounterRelease.remove.result","protocol_bot=release-remove pending=false accepted="+accepted+" object="+target);
        return SCRIPT_CONTINUE;
    }
    private String publicPortalPose(obj_id p,location local) throws InterruptedException {
        obj_id root=getTopMostContainer(p);
        if(!isIdValid(root) || local==null || !isIdValid(local.cell))return " public_pose=false";
        String family=getStringObjVar(root,"instance_name");
        vector authored;
        if("myyydril_caverns".equals(family))authored=new vector(-4,-4,-12);
        else if("nova_orion_station".equals(family))authored=new vector(62.7f,.9f,-33.5f);
        else return " public_pose=false";
        transform frame=getTransform_o2w(local.cell);
        if(frame==null)return " public_pose=false";
        vector expected=frame.rotateTranslate_l2p(authored);
        vector roundtrip=frame.rotateTranslate_p2l(expected);
        location world=getWorldLocation(p);
        float[] surface=sampleManagedPublicEntrance(p);
        boolean sampled=surface!=null && surface.length==3;
        return " public_pose=true public_template="+getTemplateName(root)+
            " public_expected_world_x="+expected.x+" public_expected_world_y="+expected.y+" public_expected_world_z="+expected.z+
            " public_roundtrip_x="+roundtrip.x+" public_roundtrip_y="+roundtrip.y+" public_roundtrip_z="+roundtrip.z+
            " public_actual_world_x="+world.x+" public_actual_world_y="+world.y+" public_actual_world_z="+world.z+
            " public_surface="+sampled+" public_surface_x="+(sampled?surface[0]:Float.NaN)+
            " public_surface_y="+(sampled?surface[1]:Float.NaN)+" public_surface_z="+(sampled?surface[2]:Float.NaN);
    }
    // This diagnostic mutates only an authenticated dedicated bot in a copied
    // Rryatt world. It never enters a role image or alters a gameplay object.
    // Recorded Falcon fixture actions use production allocation and expiry.
    private boolean hostedActor(obj_id p) throws InterruptedException {
        return p!=null && isPlayerConnected(p) && "dungeon1".equals(getCurrentSceneName()) &&
            getCurrentZoneInstanceId()==0 && hasScript(p,"fixture.protocol_bot") &&
            "npe_space_station".equals(getStringObjVar(getTopMostContainer(p),"instance_name"));
    }
    public String hostedSelection(String value) throws InterruptedException {
        String[] fields=identity(value,"hostedSelection");obj_id p=player(fields);
        if(!hostedActor(p)) return "protocol_bot=invalid-hosted-scope";
        int now=getGameTime();String result=utils.getStringScriptVar(p,"fixture.hosted.result");
        int sampled=utils.getIntScriptVar(p,"fixture.hosted.sampled");
        if(result!=null && now>=sampled && now-sampled<60) return result;
        // Console/worker census round trips can outlast a one-second native
        // hint. Poll on the ordinary game event loop and retain a diagnostic
        // receipt only; never extend or reuse a native admission/selection hint.
        if(!utils.hasScriptVar(p,"fixture.hosted.pending")) {
            int serial=utils.getIntScriptVar(p,"fixture.hosted.serial")+1;
            if(serial<=0) return "protocol_bot=invalid-hosted-serial";
            utils.setScriptVar(p,"fixture.hosted.serial",serial);utils.setScriptVar(p,"fixture.hosted.pending",serial);
            dictionary params=new dictionary();params.put("actor",fields[0]+":"+fields[1]+":"+fields[2]);
            params.put("serial",serial);params.put("started",now);params.put("polls",0);
            params.put("canonical","0");params.put("family","0");params.put("unknown","0");
            if(!messageTo(p,"fixtureHostedSelectionPoll",params,0.1f,false)) return "protocol_bot=invalid-hosted-schedule";
        }
        return "protocol_bot=hosted-selection canonical=0 family=0 unknown=0";
    }
    // Native JNI: pending=0, busy=-2 and unavailable=-3 can clear after a
    // fresh content sample. Denied=-1 and malformed statuses stay terminal.
    private boolean hostedPending(long value) {
        return value==0 || value==-2 || value==-3;
    }
    public int fixtureHostedSelectionPoll(obj_id self,dictionary params) throws InterruptedException {
        obj_id p=params==null?null:player(identity(params.getString("actor"),"hostedSelection"));
        if(!hostedActor(p) || !self.equals(p) || params.getInt("serial")!=utils.getIntScriptVar(p,"fixture.hosted.pending")) return SCRIPT_CONTINUE;
        int now=getGameTime(),polls=params.getInt("polls");
        long canonical=Long.parseLong(params.getString("canonical"));
        long family=Long.parseLong(params.getString("family")),unknown=Long.parseLong(params.getString("unknown"));
        if(hostedPending(canonical)) canonical=requestZoneInstance("space_npe_falcon");
        if(hostedPending(family)) family=requestZoneInstance("space_npe_falcon","npe_space");
        if(hostedPending(unknown)) unknown=requestZoneInstance("space_npe_falcon","fixture_unknown_family");
        if((hostedPending(canonical) || hostedPending(family) || hostedPending(unknown)) && polls<200 && now>=params.getInt("started") && now-params.getInt("started")<30) {
            params.put("canonical",Long.toString(canonical));params.put("family",Long.toString(family));params.put("unknown",Long.toString(unknown));
            params.put("polls",polls+1);messageTo(p,"fixtureHostedSelectionPoll",params,0.1f,false);return SCRIPT_CONTINUE;
        }
        utils.setScriptVar(p,"fixture.hosted.result","protocol_bot=hosted-selection canonical="+canonical+" family="+family+
            " unknown="+unknown+" sampled="+now+" polls="+polls);
        utils.setScriptVar(p,"fixture.hosted.sampled",now);utils.removeScriptVar(p,"fixture.hosted.pending");
        return SCRIPT_CONTINUE;
    }
    public String privateSoloEligibility(String value) throws InterruptedException {
        obj_id p=player(identity(value,"privateSoloEligibility"));
        if(p==null || !isPlayerConnected(p)) return "protocol_bot=invalid-private-scope";
        return "protocol_bot=private-eligibility mtp="+instance.isPrivateInstanceEntryEligible(p,"mtp_hideout_instance")+
            " obiwan="+instance.isPrivateInstanceEntryEligible(p,"obiwan_crystal_cave")+
            " group="+getGroupObject(p)+" solo="+isSoloInstanceEligible(p);
    }
    private String privateSoloRequest(String value,String method,String family) throws InterruptedException {
        obj_id p=player(identity(value,method));
        // This live fixture action tests denial only. Ungrouped requests can
        // start quests/sessions and need their own authored-content scenario.
        if(p==null || !isPlayerConnected(p) || isSoloInstanceEligible(p) || instance.isRequestPending(p) ||
           !("mtp_hideout_instance".equals(family) || "obiwan_crystal_cave".equals(family)))
            return "protocol_bot=invalid-private-scope";
        boolean accepted=instance.requestInstanceMovement(p,family);
        // Stop an unexpected queued request before any asynchronous selection.
        // A test failure must not send a fixture actor into unprepared content.
        if(accepted) instance.setRequestResolved(p);
        return "protocol_bot=private-request family="+family+" accepted="+accepted+
            " pending="+instance.isRequestPending(p)+" query="+utils.hasScriptVar(p,instance.REQUEST_QUERY);
    }
    public String privateSoloMtp(String value) throws InterruptedException {
        return privateSoloRequest(value,"privateSoloMtp","mtp_hideout_instance");
    }
    public String privateSoloObiwan(String value) throws InterruptedException {
        return privateSoloRequest(value,"privateSoloObiwan","obiwan_crystal_cave");
    }
    private boolean privateMtpScope() throws InterruptedException {
        return "WGC_AE80ACB41011".equals(getConfigSetting("dbProcess","schemaOwner")) &&
            "1".equals(getConfigSetting("GameServer","capacityPrivateMtpFixture"));
    }
    private obj_id privateMtpPlayer(String value,String method) throws InterruptedException {
        obj_id p=player(identity(value,method));
        return isIdValid(p) && isPlayerConnected(p) && privateMtpScope() ? p : null;
    }
    private boolean privateMtpQuiet(obj_id p) throws InterruptedException {
        return isIdValid(p) && isSoloInstanceEligible(p) && getState(p,STATE_COMBAT)==0 &&
            !hasObjVar(p,"capacity.groupTransfer.id") && !hasObjVar(p,"hasOutstandingRequestSceneTransfer");
    }
    private boolean privateMtpWorld() throws InterruptedException {
        return getCurrentZoneInstanceId()==0 || (getCurrentZoneInstanceId()>0 &&
            isManagedHostedPrivateEntryEnabled("mtp_hideout_instance"));
    }
    private obj_id privateMtpRoot(obj_id p) throws InterruptedException {
        if(!isIdValid(p) || !"dungeon1".equals(getCurrentSceneName()) || !privateMtpWorld()) return null;
        obj_id root=getTopMostContainer(p);
        return isIdValid(root) && root.isAuthoritative() && hasScript(root,"systems.instance.instance_manager") &&
            getZoneInstanceId(root)==getCurrentZoneInstanceId() &&
            "mtp_hideout_instance".equals(instance.getInstanceName(root)) ? root : null;
    }
    private String privateMtpQueue(obj_id p,String actor,String action,String handler) throws InterruptedException {
        int prior=getIntObjVar(p,"fixture.privateRequestSerial");
        if(prior<0 || prior==Integer.MAX_VALUE || !hasScript(p,"fixture.protocol_bot") ||
            !setObjVar(p,"fixture.privateRequestSerial",prior+1)) return "protocol_bot=invalid-private-mtp-request";
        dictionary params=new dictionary();params.put("actor",actor);params.put("serial",prior+1);
        params.put("scene",getCurrentSceneName());params.put("world",Long.toString(getCurrentZoneInstanceId()));
        obj_id top=getTopMostContainer(p);params.put("top",isIdValid(top)?top:p);
        obj_id root=privateMtpRoot(p);
        if(isIdValid(root)){
            params.put("lease_root",root);params.put("lease_session",instance.getPrivateInstanceSession(root));
            params.put("lease_start",instance.getInstanceStartTime(root));
        }
        utils.setScriptVar(p,"fixture.privateMtp.action",action);utils.setScriptVar(p,"fixture.privateMtp.result","queued");
        boolean queued=messageTo(p,handler,params,0.1f,false);
        return "protocol_bot=private-mtp-request accepted="+queued+" queued="+queued+" serial="+(prior+1);
    }
    private obj_id privateMtpRequestActor(obj_id self,dictionary params,String method) throws InterruptedException {
        if(params==null || !(params.get("serial") instanceof Integer)) return null;
        obj_id p=privateMtpPlayer(params.getString("actor"),method);
        if(!isIdValid(p) || !self.equals(p) || params.getInt("serial")!=getIntObjVar(p,"fixture.privateRequestSerial") ||
            params.getInt("serial")<=getIntObjVar(p,"fixture.privateHandledSerial") ||
            !setObjVar(p,"fixture.privateHandledSerial",params.getInt("serial"))) return null;
        return p;
    }
    private boolean privateMtpOrigin(obj_id p,dictionary params) throws InterruptedException {
        obj_id top=getTopMostContainer(p);if(!isIdValid(top)) top=p;
        return getCurrentSceneName().equals(params.getString("scene")) &&
            Long.toString(getCurrentZoneInstanceId()).equals(params.getString("world")) &&
            top.equals(params.getObjId("top"));
    }
    private String privateMtpError(String stage,Throwable error) {
        String detail=error.getMessage();if(detail==null) detail="none";
        detail=detail.replaceAll("[^A-Za-z0-9_.$()/;,:-]","_");if(detail.length()>200) detail=detail.substring(0,200);
        return "protocol_bot=private-mtp-error accepted=false stage="+stage+" error_class="+error.getClass().getName()+" detail="+detail;
    }
    public String privateMtpPrepare(String value) throws InterruptedException {
        obj_id p=privateMtpPlayer(value,"privateMtpPrepare");
        if(!privateMtpQuiet(p) || instance.isRequestPending(p) || !"dungeon1".equals(getCurrentSceneName()) ||
            !privateMtpWorld() || !"npe_space_station".equals(getStringObjVar(getTopMostContainer(p),"instance_name")))
            return "protocol_bot=invalid-private-mtp-setup";
        int phase=getIntObjVar(p,npe.VAR_NPE_PHASE);
        if(phase==4 && getIntObjVar(p,"fixture.privateMtp.enabled")==1)
            return "protocol_bot=private-mtp-setup accepted=true retained=true version=actor-r5";
        if(phase!=3 || hasObjVar(p,"fixture.privateMtp")) return "protocol_bot=invalid-private-mtp-phase";
        boolean accepted=setObjVar(p,"fixture.privateMtp.home",getTopMostContainer(p)) &&
            setObjVar(p,"fixture.privateMtp.homeWorld",Long.toString(getCurrentZoneInstanceId())) &&
            setObjVar(p,"fixture.privateMtp.enabled",1) && setObjVar(p,npe.VAR_NPE_PHASE,4);
        if(!accepted) removeObjVar(p,"fixture.privateMtp");
        return "protocol_bot=private-mtp-setup accepted="+accepted+" phase="+getIntObjVar(p,npe.VAR_NPE_PHASE)+" version=actor-r5";
    }
    public String privateMtpEnter(String value) throws InterruptedException {
        try {
        obj_id p=privateMtpPlayer(value,"privateMtpEnter");
        if(!privateMtpQuiet(p) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 || getIntObjVar(p,npe.VAR_NPE_PHASE)!=4 ||
            !privateMtpWorld() || instance.isRequestPending(p) || isIdValid(privateMtpRoot(p)) ||
            !("dungeon1".equals(getCurrentSceneName()) || "corellia".equals(getCurrentSceneName())))
            return "protocol_bot=invalid-private-mtp-entry";
        return privateMtpQueue(p,value,"enter","fixturePrivateMtpEnter");
        } catch(RuntimeException error){return privateMtpError("entry-console",error);}
        catch(LinkageError error){return privateMtpError("entry-console",error);}
    }
    public int fixturePrivateMtpEnter(obj_id self,dictionary params) throws InterruptedException {
        obj_id p=privateMtpRequestActor(self,params,"privateMtpEnter");
        if(!isIdValid(p)) return SCRIPT_CONTINUE;
        if(!privateMtpQuiet(p) || !privateMtpOrigin(p,params) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 ||
            getIntObjVar(p,npe.VAR_NPE_PHASE)!=4 || instance.isRequestPending(p) || isIdValid(privateMtpRoot(p))) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        utils.setScriptVar(p,"fixture.privateMtp.result","issued");
        try {
            if(!instance.requestInstanceMovement(p,"mtp_hideout_instance")) utils.setScriptVar(p,"fixture.privateMtp.result","refused");
        } catch(RuntimeException | LinkageError error) {
            utils.setScriptVar(p,"fixture.privateMtp.result","error:"+error.getClass().getName());
            utils.setScriptVar(p,"fixture.privateMtp.diagnostic",privateMtpError("entry-actor",error));
        }
        return SCRIPT_CONTINUE;
    }
    public String privateMtpInspect(String value) throws InterruptedException {
        String[] fields=identity(value,"privateMtpInspect");
        if(fields==null || !privateMtpScope()) return "protocol_bot=invalid-private-mtp-scope";
        obj_id p=player(fields);
        if(!isIdValid(p)) {
            obj_id candidate=obj_id.getObjId(Long.parseLong(fields[0]));
            return isIdValid(candidate) && candidate.isAuthoritative() ? "protocol_bot=invalid-identity" : "protocol_bot=absent";
        }
        obj_id root=privateMtpRoot(p);
        boolean inside=isIdValid(root);
        return "protocol_bot=private-mtp version=actor-r5 connected="+isPlayerConnected(p)+" inside="+inside+" root="+root+
            " owner="+(inside?instance.getInstanceOwner(root):null)+" session="+(inside?instance.getPrivateInstanceSession(root):0)+
            " sequence="+(inside?instance.getPrivateInstanceSequence(root):0)+" start="+(inside?instance.getInstanceStartTime(root):-1)+
            " limit="+(inside?instance.getInstancePlayerCap(root):0)+
            " owned="+(inside && p.equals(instance.getInstanceOwner(root)))+
            " pending="+instance.isRequestPending(p)+" enabled="+getIntObjVar(p,"fixture.privateMtp.enabled")+
            " request_serial="+getIntObjVar(p,"fixture.privateRequestSerial")+" request_result="+utils.getStringScriptVar(p,"fixture.privateMtp.result")+
            " phase="+getIntObjVar(p,npe.VAR_NPE_PHASE)+" scene="+getCurrentSceneName()+" instance="+getCurrentZoneInstanceId()+
            " managed="+isManagedHostedPrivateEntryEnabled("mtp_hideout_instance");
    }
    public String privateMtpLeave(String value) throws InterruptedException {
        try {
        obj_id p=privateMtpPlayer(value,"privateMtpLeave");obj_id root=privateMtpRoot(p);
        if(!privateMtpQuiet(p) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 || instance.isRequestPending(p) ||
            getIntObjVar(p,npe.VAR_NPE_PHASE)!=4 || !isIdValid(root) || !p.equals(instance.getInstanceOwner(root)) ||
            instance.getPrivateInstanceSession(root)<=0 || instance.getInstanceStartTime(root)<0)
            return "protocol_bot=invalid-private-mtp-leave";
        // Explicit fixture setup for active-room re-entry. Use the original
        // per-player exit; leave ownership, session, timer and encounter alone.
        return privateMtpQueue(p,value,"leave-retained","fixturePrivateMtpLeave");
        } catch(RuntimeException error){return privateMtpError("leave-console",error);}
        catch(LinkageError error){return privateMtpError("leave-console",error);}
    }
    public int fixturePrivateMtpLeave(obj_id self,dictionary params) throws InterruptedException {
        obj_id p=privateMtpRequestActor(self,params,"privateMtpLeave");
        if(!isIdValid(p)) return SCRIPT_CONTINUE;
        obj_id root=privateMtpRoot(p);
        if(!privateMtpQuiet(p) || !privateMtpOrigin(p,params) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 ||
            getIntObjVar(p,npe.VAR_NPE_PHASE)!=4 || instance.isRequestPending(p) || !isIdValid(root) ||
            !root.equals(params.getObjId("lease_root")) || instance.getPrivateInstanceSession(root)!=params.getInt("lease_session") ||
            instance.getInstanceStartTime(root)!=params.getInt("lease_start") || !p.equals(instance.getInstanceOwner(root))) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        utils.setScriptVar(p,"fixture.privateMtp.result","issued");
        try {instance.requestExitPlayer("mtp_hideout_instance",p);}
        catch(RuntimeException | LinkageError error){
            utils.setScriptVar(p,"fixture.privateMtp.result","error:"+error.getClass().getName());
            utils.setScriptVar(p,"fixture.privateMtp.diagnostic",privateMtpError("leave-actor",error));
        }
        return SCRIPT_CONTINUE;
    }
    public String privateMtpClose(String value) throws InterruptedException {
        try {
        obj_id p=privateMtpPlayer(value,"privateMtpClose");
        obj_id root=privateMtpRoot(p);
        if(!privateMtpQuiet(p) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 || instance.isRequestPending(p) ||
            !isIdValid(root) || !p.equals(instance.getInstanceOwner(root)) || instance.getPrivateInstanceSession(root)<=0)
            return "protocol_bot=invalid-private-mtp-close";
        return privateMtpQueue(p,value,"close","fixturePrivateMtpClose");
        } catch(RuntimeException error){return privateMtpError("close-console",error);}
        catch(LinkageError error){return privateMtpError("close-console",error);}
    }
    public int fixturePrivateMtpClose(obj_id self,dictionary params) throws InterruptedException {
        obj_id p=privateMtpRequestActor(self,params,"privateMtpClose");
        if(!isIdValid(p)) return SCRIPT_CONTINUE;
        obj_id root=privateMtpRoot(p);
        if(!privateMtpQuiet(p) || !privateMtpOrigin(p,params) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 ||
            instance.isRequestPending(p) || !isIdValid(root) || !root.equals(params.getObjId("lease_root")) ||
            instance.getPrivateInstanceSession(root)!=params.getInt("lease_session") || !p.equals(instance.getInstanceOwner(root))) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        utils.setScriptVar(p,"fixture.privateMtp.result","issued");
        try {instance.closeOwnedInstance(p,"mtp_hideout_instance");}
        catch(RuntimeException | LinkageError error){
            utils.setScriptVar(p,"fixture.privateMtp.result","error:"+error.getClass().getName());
            utils.setScriptVar(p,"fixture.privateMtp.diagnostic",privateMtpError("close-actor",error));
        }
        return SCRIPT_CONTINUE;
    }
    public String privateMtpHome(String value) throws InterruptedException {
        obj_id p=privateMtpPlayer(value,"privateMtpHome");
        if(!privateMtpQuiet(p) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 || instance.isRequestPending(p) ||
            !"corellia".equals(getCurrentSceneName()) || getCurrentZoneInstanceId()!=0 || getIntObjVar(p,npe.VAR_NPE_PHASE)!=4)
            return "protocol_bot=invalid-private-mtp-return";
        location here=getLocation(p);
        obj_id home=getObjIdObjVar(p,"fixture.privateMtp.home");
        String homeText=hasObjVar(p,"fixture.privateMtp.homeWorld")?getStringObjVar(p,"fixture.privateMtp.homeWorld"):"0";
        long homeWorld;
        try {
            if(homeText==null || !homeText.matches("0|[1-9][0-9]{0,18}"))return "protocol_bot=invalid-private-mtp-home-world";
            homeWorld=Long.parseLong(homeText);
        } catch(NumberFormatException error){return "protocol_bot=invalid-private-mtp-home-world";}
        if(homeWorld<0 || (homeWorld>0 && !isManagedHostedPrivateEntryEnabled("mtp_hideout_instance")))
            return "protocol_bot=invalid-private-mtp-home-world";
        if(!isIdValid(home) || Math.abs(here.x+516)>5 || Math.abs(here.y-28)>5 || Math.abs(here.z+4433)>5)
            return "protocol_bot=invalid-private-mtp-exit";
        dictionary entrance=npe.getNpeInstanceInfo(npe.DUNGEON_SPACE_STATION);
        location local=entrance.getLocation("cell_loc");String room=entrance.getString("cell");
        if(local==null || !"hangarbay2".equals(room)) return "protocol_bot=invalid-private-mtp-home";
        return privateMtpQueue(p,value,"home","fixturePrivateMtpHome");
    }
    public int fixturePrivateMtpHome(obj_id self,dictionary params) throws InterruptedException {
        obj_id p=privateMtpRequestActor(self,params,"privateMtpHome");
        if(!isIdValid(p)) return SCRIPT_CONTINUE;
        if(!privateMtpQuiet(p) || !privateMtpOrigin(p,params) || getIntObjVar(p,"fixture.privateMtp.enabled")!=1 ||
            instance.isRequestPending(p) || !"corellia".equals(getCurrentSceneName()) ||
            getCurrentZoneInstanceId()!=0 || getIntObjVar(p,npe.VAR_NPE_PHASE)!=4) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        obj_id home=getObjIdObjVar(p,"fixture.privateMtp.home");location here=getLocation(p);
        String homeText=hasObjVar(p,"fixture.privateMtp.homeWorld")?getStringObjVar(p,"fixture.privateMtp.homeWorld"):"0";
        long homeWorld;
        try {
            if(homeText==null || !homeText.matches("0|[1-9][0-9]{0,18}"))throw new NumberFormatException();
            homeWorld=Long.parseLong(homeText);
        } catch(NumberFormatException error) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        dictionary entrance=npe.getNpeInstanceInfo(npe.DUNGEON_SPACE_STATION);
        location local=entrance.getLocation("cell_loc");String room=entrance.getString("cell");
        if(!isIdValid(home) || homeWorld<0 ||
            (homeWorld>0 && !isManagedHostedPrivateEntryEnabled("mtp_hideout_instance")) ||
            here==null || Math.abs(here.x+516)>5 || Math.abs(here.y-28)>5 || Math.abs(here.z+4433)>5 ||
            local==null || !"hangarbay2".equals(room)) {
            utils.setScriptVar(p,"fixture.privateMtp.result","refused");return SCRIPT_CONTINUE;
        }
        utils.setScriptVar(p,"fixture.privateMtp.result","issued");
        setObjVar(p,npe.VAR_NPE_PHASE,3);attachScript(p,npe.SCRIPT_PUBLIC_TRAVEL);attachScript(p,"npe.trigger_journal");
        try {
            // A positive public host requires ordinary native admission. The
            // fixture's remembered station is an assertion, never a warp grant.
            boolean accepted=homeWorld>0 ? npe.requestPublicStationTravel(p,npe.DUNGEON_SPACE_STATION) :
                warpPlayerToInstance(p,"dungeon1",0,0,0,0,home,room,local.x,local.y,local.z,"msgNpeInstanceTravelComplete",true);
            if(accepted) removeObjVar(p,"fixture.privateMtp");
            else {setObjVar(p,npe.VAR_NPE_PHASE,4);utils.setScriptVar(p,"fixture.privateMtp.result","refused");}
        } catch(RuntimeException | LinkageError error) {
            setObjVar(p,npe.VAR_NPE_PHASE,4);
            utils.setScriptVar(p,"fixture.privateMtp.result","error:"+error.getClass().getName());
            utils.setScriptVar(p,"fixture.privateMtp.diagnostic",privateMtpError("home-actor",error));
        }
        return SCRIPT_CONTINUE;
    }
    private boolean falconActor(obj_id p) throws InterruptedException {
        return isIdValid(p) && isPlayerConnected(p) && !isIdValid(getGroupObject(p)) &&
            getState(p,STATE_COMBAT)==0 && !hasObjVar(p,"capacity.groupTransfer.id") &&
            !hasObjVar(p,"hasOutstandingRequestSceneTransfer");
    }
    private obj_id falconRoom(obj_id p) throws InterruptedException {
        if(!falconActor(p) || !"space_npe_falcon".equals(getCurrentSceneName()) || getCurrentZoneInstanceId()<=0) return null;
        obj_id room=getTopMostContainer(p);
        obj_id[] ids=space_dungeon.getParticipantIds(room);
        return isIdValid(room) && room.isAuthoritative() && getZoneInstanceId(room)==getCurrentZoneInstanceId() &&
            p.equals(getOwner(room)) && "npe_space".equals(space_dungeon.getDungeonName(room)) &&
            space_dungeon.getDungeonSessionId(room)>0 &&
            space_dungeon.getDungeonSessionId(room)==space_dungeon.getDungeonSessionId(p) &&
            room.equals(space_dungeon.getDungeonIdForPlayer(p)) && ids!=null && ids.length==1 && p.equals(ids[0]) ? room : null;
    }
    public String falconEnter(String value) throws InterruptedException {
        obj_id p=player(identity(value,"falconEnter"));
        if(!falconActor(p) || !"npe_space_station".equals(fixtureFamily(p))) return "protocol_bot=invalid-setup";
        // Match the authored hangar_exit_terminal setup so the driver's normal
        // clientReady message reaches the existing Falcon sequencer.
        detachScript(p,"npe.han_solo_experience_player");
        attachScript(p,"npe.npe_falcon_player");
        return "protocol_bot=falcon-entry accepted="+npe.movePlayerFromHangarToFalcon(p);
    }
    public String falconInspect(String value) throws InterruptedException {
        obj_id p=player(identity(value,"falconInspect"));obj_id room=falconRoom(p);
        if(!isIdValid(room)) return "protocol_bot=invalid-room";
        return "protocol_bot=falcon-room player="+p+" room="+room+" owner="+getOwner(room)+
            " session="+space_dungeon.getDungeonSessionId(room)+" player_session="+space_dungeon.getDungeonSessionId(p)+
            " participants=1 phase="+getIntObjVar(p,npe.VAR_NPE_PHASE)+
            " instance="+getCurrentZoneInstanceId()+" cell="+getLocation(p).cell+
            " end="+getIntObjVar(room,space_dungeon.VAR_DUNGEON_END_TIME)+" now="+getGameTime()+
            " sequence_player="+utils.getObjIdScriptVar(room,"npe.player")+
            " sequence_started="+utils.hasScriptVar(room,"npe.sequence.started")+
            " manager_session="+utils.getIntScriptVar(room,"npe.falconSession")+
            " main_index="+utils.getIntScriptVar(room,"intMainIndex")+
            " han="+utils.getObjIdScriptVar(room,"objHanSolo")+
            " chewie="+utils.getObjIdScriptVar(room,"objChewie")+
            " event_started="+utils.getBooleanScriptVar(p,"npe.falconEventStarted");
    }
    public String falconArm(String value) throws InterruptedException {
        obj_id p=player(identity(value,"falconArm"));obj_id room=falconRoom(p);
        if(!isIdValid(room) || getIntObjVar(p,npe.VAR_NPE_PHASE)!=2 ||
            getIntObjVar(room,space_dungeon.VAR_DUNGEON_END_TIME)-getGameTime()<120) return "protocol_bot=invalid-room";
        setObjVar(room,"retirementFixture.player",p);
        setObjVar(room,"retirementFixture.realSession",space_dungeon.getDungeonSessionId(room));
        return "protocol_bot=falcon-expiry-armed accepted=true room="+room+" session="+space_dungeon.getDungeonSessionId(room);
    }
    public String falconExit(String value) throws InterruptedException {
        obj_id p=player(identity(value,"falconExit"));
        if(!falconActor(p)) return "protocol_bot=invalid-setup";
        // A prior accepted exit may have saved phase 3 before leaving its NPC
        // ship. Retry only that dedicated actor's unowned, interrupted exit.
        obj_id top=getTopMostContainer(p);
        boolean retry=falconActor(p) && "space_npe_falcon".equals(getCurrentSceneName()) &&
            getCurrentZoneInstanceId()>0 && getIntObjVar(p,npe.VAR_NPE_PHASE)==3 &&
            isIdValid(top) && top.isAuthoritative() && !isIdValid(getOwner(top)) &&
            "npe_space".equals(space_dungeon.getDungeonName(top)) &&
            !isIdValid(space_dungeon.getDungeonIdForPlayer(p));
        if(!isIdValid(falconRoom(p)) && !retry) return "protocol_bot=invalid-room";
        return "protocol_bot=falcon-exit accepted="+npe.movePlayerFromFalconToSharedStation(p);
    }
    public String worldSaveStamp(String value) throws InterruptedException {
        obj_id p=player(identity(value,"worldSaveStamp"));
        if(!isIdValid(p) || !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) ||
                getCurrentZoneInstanceId()<=0 || getZoneInstanceId(p)!=getCurrentZoneInstanceId())
            return "protocol_bot=invalid-setup";
        int stamp=getIntObjVar(p,"fixture.worldSaveStamp")+1;
        if(stamp<=0 || stamp>1000000) return "protocol_bot=invalid-setup";
        setObjVar(p,"fixture.worldSaveStamp",stamp);
        return "protocol_bot=world-save-stamp accepted=true value="+stamp;
    }
    public String worldSaveClear(String value) throws InterruptedException {
        obj_id p=player(identity(value,"worldSaveClear"));
        if(!isIdValid(p) || !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) ||
                getCurrentZoneInstanceId()<=0 || getZoneInstanceId(p)!=getCurrentZoneInstanceId())
            return "protocol_bot=invalid-setup";
        removeObjVar(p,"fixture.worldSaveStamp");
        return "protocol_bot=world-save-clear accepted=true";
    }
    private String fixtureFamily(obj_id p) throws InterruptedException {
        if("kashyyyk_rryatt_trail".equals(getLocation(p).area))
            return space_dungeon.isCurrentRryattTrailController(p)?"rryatt_trail":null;
        return getStringObjVar(getTopMostContainer(p),"instance_name");
    }
    public String rryattDiagnostics(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattDiagnostics"));
        if(!kashyyykActor(p) || !"kashyyyk_main".equals(getCurrentSceneName())) return "protocol_bot=invalid-setup";
        if(!hasScript(p,"fixture.protocol_bot")) attachScript(p,"fixture.protocol_bot");
        utils.setScriptVar(p,"fixture.rryatt.count",-1);
        utils.setScriptVar(p,"fixture.rryatt.query",getClusterWideData("public_instances","rryatt_trail_*",false,p));
        return "protocol_bot=rryatt-observation accepted=true";
    }
    public int OnClusterWideDataResponse(obj_id self,String manager,String name,int query,String[] elements,dictionary[] data,int lock) throws InterruptedException {
        if(!"public_instances".equals(manager) || !utils.hasScriptVar(self,"fixture.rryatt.query") ||
                query!=utils.getIntScriptVar(self,"fixture.rryatt.query")) return SCRIPT_CONTINUE;
        if(player(identity(self+":"+Integer.toUnsignedLong(getPlayerStationId(self))+":"+getPlayerFullName(self),""))==null)
            return SCRIPT_CONTINUE;
        utils.setScriptVar(self,"fixture.rryatt.count",data==null?-2:data.length);
        String summary="";
        if(data!=null && elements!=null && data.length<=96 && elements.length==data.length)
            for(int i=0;i<data.length;i++) summary+=(i==0?"":",")+elements[i]+":"+data[i].getString("scene")+":"+
                    data[i].getString("instance_name")+":"+data[i].getString("zone_instance_id")+":"+data[i].getInt("buildout_row");
        utils.setScriptVar(self,"fixture.rryatt.summary",summary.length()==0?"empty":summary);
        return SCRIPT_CONTINUE;
    }
    private boolean kashyyykActor(obj_id p) throws InterruptedException {return kashyyykActor(p,false);}
    private boolean kashyyykActor(obj_id p,boolean grouped) throws InterruptedException {
        return isIdValid(p) && isPlayerConnected(p) && (grouped || !isIdValid(getGroupObject(p))) &&
                !isIdValid(space_transition.getContainingShip(p)) && getState(p,STATE_COMBAT)==0 &&
                !hasObjVar(p,"capacity.groupTransfer.id") && !hasObjVar(p,"hasOutstandingRequestSceneTransfer") &&
                (getCurrentZoneInstanceId()==0 || ("kashyyyk_rryatt_trail".equals(getCurrentSceneName()) && "true".equals(getConfigSetting("GameServer","capacityRryattInstancesEnabled"))));
    }
    public String kashyyykSetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"kashyyykSetup"));
        if(!kashyyykActor(p) || !"dungeon1".equals(getCurrentSceneName()) ||
                !"npe_space_station".equals(getStringObjVar(getTopMostContainer(p),"instance_name")))
            return "protocol_bot=invalid-setup";
        // Recorded bot-only setup into the original authored Kachirho return.
        String[] point=split(dataTableGetString("datatables/travel/zone_transition.iff","rryatt_kachirho","destination"),':');
        if(point.length!=4 || !"kashyyyk_main".equals(point[0])) return "protocol_bot=invalid-entrance";
        setObjVar(p,npe.VAR_NPE_PHASE,4);
        boolean accepted=warpPlayerToInstance(p,point[0],0L,Float.parseFloat(point[1]),Float.parseFloat(point[2]),
                Float.parseFloat(point[3]),null,0,0,0,"",true);
        return "protocol_bot=kashyyyk-setup accepted="+accepted;
    }
    private int rryattGateApproach(boolean same,int request,int seen,int used) {
        return same && request==seen ? used : 0;
    }
    private String rryattGate(obj_id p,boolean exit) throws InterruptedException {
        String scene=exit?"kashyyyk_rryatt_trail":"kashyyyk_main";
        if(!kashyyykActor(p,true) || !scene.equals(getCurrentSceneName())) return "protocol_bot=invalid-setup";
        obj_id root=exit?getObjIdObjVar(p,space_dungeon.INSTANCE_ID):p;
        if(exit && !space_dungeon.isCurrentRryattTrailController(p)) return "protocol_bot=invalid-linked-controller";
        int anchor=exit?locations.getBuildoutAreaRow(root):-1;
        obj_id[] gates=getAllObjectsWithScript(getLocation(root),1000.0f,"systems.movement.zone_transition");
        obj_id found=null;
        if(gates!=null) for(obj_id gate:gates) if(isIdValid(gate) && gate.isAuthoritative() &&
                (exit?"rryatt_kachirho":"kachirho_rryatt").equals(getStringObjVar(gate,"zoneLine")) &&
                (!exit || locations.getBuildoutAreaRow(gate)==anchor)) {
            if(found!=null) return "protocol_bot=ambiguous-gate";
            found=gate;
        }
        if(!isIdValid(found)) return "protocol_bot=no-rryatt-gate";
        // Bound fixture placement to nearby approaches. Keep native LOS/range
        // checks enabled; neither the gate nor its collision is changed.
        obj_id previous=utils.getObjIdScriptVar(p,"fixture.rryatt.gate");
        // A completed normal menu request starts a new bounded approach cycle.
        // Reusing the old counter can skip the only visible side of the gate.
        int request=exit?0:utils.getIntScriptVar(p,"rryatt.entrySerial");
        int seen=utils.getIntScriptVar(p,"fixture.rryatt.gateRequest");
        int approach=rryattGateApproach(found.equals(previous),request,seen,utils.getIntScriptVar(p,"fixture.rryatt.approach"));
        utils.setScriptVar(p,"fixture.rryatt.gateRequest",request);
        if(approach<0 || approach>=8) return "protocol_bot=no-visible-rryatt-approach";
        float[][] offsets={{0.0f,4.0f},{0.0f,-4.0f},{4.0f,0.0f},{-4.0f,0.0f}};
        vector point=getTransform_o2w(found).rotateTranslate_l2p(new vector(offsets[approach%4][0],0.0f,offsets[approach%4][1]));
        float terrain=getHeightAtLocation(point.x,point.z);

        location l=getLocation(found);l.x=point.x;l.y=approach>=4?terrain:point.y;l.z=point.z;
        utils.setScriptVar(p,"fixture.rryatt.gate",found);
        utils.setScriptVar(p,"fixture.rryatt.approach",approach+1);
        boolean accepted=warpPlayerToInstance(p,scene,getZoneInstanceId(p),l.x,l.y,l.z,null,l.x,l.y,l.z,"",true);
        return "protocol_bot=rryatt-gate-setup accepted="+accepted+" target="+found+" approach="+approach+
                " x="+l.x+" y="+l.y+" z="+l.z+" terrain="+terrain;
    }
    public String rryattSetup(String value) throws InterruptedException {
        return rryattGate(player(identity(value,"rryattSetup")),false);
    }
    public String rryattExitSetup(String value) throws InterruptedException {
        return rryattGate(player(identity(value,"rryattExitSetup")),true);
    }
    public String rryattAudit(String value) throws InterruptedException {
        if(identity(value,"rryattAudit")==null || !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) ||
                (getCurrentZoneInstanceId()!=0 && !"true".equals(getConfigSetting("GameServer","capacityRryattInstancesEnabled")))) return "protocol_bot=invalid-audit-scope";
        obj_id[] objects=getAllObjectsWithScript(new location(0,0,0,"kashyyyk_rryatt_trail"),16000.0f,"systems.movement.zone_transition");
        String rows="";int count=0;
        if(objects!=null) for(obj_id npc:objects) if(isIdValid(npc) && npc.isAuthoritative() && isMob(npc) &&
                (hasScript(npc,"conversation.rryatt_trail_guide") || hasScript(npc,"conversation.rryatt_trail_guide_up"))) {
            if(++count>96) return "protocol_bot=invalid-guide-count";
            obj_id spawner=utils.getObjIdScriptVar(npc,"spawnedBy");
            location current=getLocation(npc),authored=isIdValid(spawner)&&exists(spawner)?getLocation(spawner):null;
            rows+=(rows.length()==0?"":",")+locations.getBuildoutAreaRow(npc)+":"+getStringObjVar(npc,"zoneLine")+":"+npc+":"+
                    current.x+":"+current.y+":"+current.z+":"+(authored==null?"missing":authored.x+":"+authored.y+":"+authored.z)+":"+isCreatureStatic(npc)+":"+spawner+":"+
                    (isIdValid(spawner)&&exists(spawner)?getStringObjVar(spawner,"spawns"):"missing")+":"+
                    (isIdValid(spawner)&&exists(spawner)&&hasScript(spawner,"npc.celebrity.celebrity_spawner"));
        }
        String roots="";
        obj_id[] controllers=getAllObjectsWithScript(new location(0,0,0,"kashyyyk_rryatt_trail"),16000.0f,"systems.movement.public_instance_setup");
        if(controllers!=null && controllers.length<=96) for(obj_id root:controllers) {
            roots+=(roots.length()==0?"":",")+root+":"+locations.getBuildoutAreaRow(root)+":"+
                hasObjVar(root,"space_dungeon.name")+":"+getStringObjVar(root,"instance_name");
        }
        int enemies=0;
        obj_id[] temporary=getAllObjectsWithScript(new location(0,0,0,"kashyyyk_rryatt_trail"),16000.0f,"fixture.protocol_bot");
        if(temporary!=null && temporary.length<=96) for(obj_id candidate:temporary)
            if(!isPlayer(candidate) && hasObjVar(candidate,"fixture.rryatt.owner")) enemies++;
        return "protocol_bot=rryatt-audit temporary_enemies="+enemies+" root_data="+(roots.length()==0?"none":roots)+" count="+count+" managed="+isManagedRryattGroupEnabled()+" set_limit="+getConfigSetting("GameServer","capacityRryattSetLimit")+" guides="+rows;
    }
    private vector rryattApproach(obj_id npc,int attempt) throws InterruptedException {
        // NPCs turn toward a player. World offsets keep successive attempts distinct.
        float[][] offsets={{0,3},{0,-3},{3,0},{-3,0},{0,1.5f},{0,-1.5f},{1.5f,0},{-1.5f,0},
                {1.5f,1.5f},{1.5f,-1.5f},{-1.5f,1.5f},{-1.5f,-1.5f},{3,3},{3,-3},{-3,3},{-3,-3}};
        if(attempt<0 || attempt>=offsets.length) throw new IllegalArgumentException("Invalid approach index");
        location l=getLocation(npc);float dx=offsets[attempt][0],dz=offsets[attempt][1];
        float y=l.y;
        if(isOnAFloor(npc) && isRelativePointOnSameFloorAsObject(npc,dx,dz))
            y=getFloorHeightAtRelativePointOnSameFloorAsObject(npc,dx,dz);
        return new vector(l.x+dx,y,l.z+dz);
    }
    private String rryattGuide(String value,int index) throws InterruptedException {
        obj_id p=player(identity(value,"rryattGuide"+index));
        if(!kashyyykActor(p,true) || !space_dungeon.isCurrentRryattTrailController(p)) return "protocol_bot=invalid-setup";
        String[] routes={"rryattOne_rryattTwo","rryattTwo_rryattOne","rryattTwo_rryattThree","rryattThree_rryattTwo",
                "rryattThree_rryattFour","rryattFour_rryattThree","rryattFour_rryattFive","rryattFive_rryattFour"};
        int[] rows={0,0,0,1,1,2,2,3};
        obj_id controller=getObjIdObjVar(p,space_dungeon.INSTANCE_ID),found=null;
        int anchor=locations.getBuildoutAreaRow(controller);
        // Discover existing authored NPCs in this linked set. Never create a
        // guide, change its scripts or bypass conversation permissions.
        obj_id[] guides=getAllObjectsWithScript(getLocation(controller),4000.0f,"systems.movement.zone_transition");
        if(guides!=null) for(obj_id guide:guides) if(isIdValid(guide) && guide.isAuthoritative() && isMob(guide) &&
                getZoneInstanceId(guide)==getZoneInstanceId(p) && locations.getBuildoutAreaRow(guide)==anchor+rows[index] &&
                routes[index].equals(getStringObjVar(guide,"zoneLine")) &&
                hasScript(guide,index%2==0?"conversation.rryatt_trail_guide":"conversation.rryatt_trail_guide_up")) {
            if(found!=null) return "protocol_bot=ambiguous-guide";
            found=guide;
        }
        if(!isIdValid(found)) return "protocol_bot=no-authored-guide route="+routes[index];
        obj_id spawner=utils.getObjIdScriptVar(found,"spawnedBy");
        if(!isIdValid(spawner) || !exists(spawner)) return "protocol_bot=missing-guide-spawner";
        location authored=getLocation(spawner),current=getLocation(found);
        if(Math.abs(authored.x-current.x)>.1f || Math.abs(authored.z-current.z)>.1f || Math.abs(authored.y-current.y)>3.0f)
            return "protocol_bot=invalid-authored-guide-position target="+found+" x="+current.x+" y="+current.y+" z="+current.z+" authored_x="+authored.x+" authored_y="+authored.y+" authored_z="+authored.z;

        obj_id previous=utils.getObjIdScriptVar(p,"fixture.rryatt.guide");
        int approach=found.equals(previous)?utils.getIntScriptVar(p,"fixture.rryatt.guideApproach"):0;
        if(approach<0 || approach>=16) return "protocol_bot=no-visible-guide-approach";
        vector point=rryattApproach(found,approach);
        location guideLoc=getLocation(found);float y=point.y;
        String start=getStringObjVar(found,"startingLocation");
        String table="datatables/travel/zone_transition.iff";
        String[] destination=split(dataTableGetString(table,routes[index],"destination"),':');
        String[] entrance=split(dataTableGetString(table,start,"destination"),':');
        if(destination.length!=4 || entrance.length!=4 || !"offset".equals(destination[0]) || !"offset".equals(entrance[0]))
            return "protocol_bot=invalid-guide-destination";
        float floor=Float.NaN;
        // Adjacent arrival guides stand on the destination's authored platform.
        // Query that floor before travel, independently of the test actor.
        if(guides!=null) for(obj_id guide:guides) if(isIdValid(guide) && guide.isAuthoritative() &&
                locations.getBuildoutAreaRow(guide)==anchor+rows[index^1] &&
                routes[index^1].equals(getStringObjVar(guide,"zoneLine"))) {
            location other=getLocation(guide);
            float dx=guideLoc.x+utils.stringToFloat(destination[1])-other.x;
            float dz=guideLoc.z+utils.stringToFloat(destination[3])-other.z;
            if(isOnAFloor(guide) && isRelativePointOnSameFloorAsObject(guide,dx,dz))
                floor=getFloorHeightAtRelativePointOnSameFloorAsObject(guide,dx,dz);
        }
        float ground=getHeightAtLocation(guideLoc.x+utils.stringToFloat(destination[1]),guideLoc.z+utils.stringToFloat(destination[3]));
        float returnGround=getHeightAtLocation(guideLoc.x+utils.stringToFloat(entrance[1]),guideLoc.z+utils.stringToFloat(entrance[3]));
        utils.setScriptVar(p,"fixture.rryatt.guide",found);
        utils.setScriptVar(p,"fixture.rryatt.guideApproach",approach+1);
        boolean accepted=warpPlayerToInstance(p,"kashyyyk_rryatt_trail",getZoneInstanceId(p),point.x,y,point.z,null,point.x,y,point.z,"",true);
        return "protocol_bot=rryatt-guide-setup accepted="+accepted+" target="+found+" route="+routes[index]+" start_route="+start+
                " guide_y="+current.y+" guide_authored_y="+authored.y+" anchor="+anchor+" floor_y="+floor+" ground_y="+ground+" return_ground_y="+returnGround+" x="+(guideLoc.x+utils.stringToFloat(destination[1]))+
                " y="+(guideLoc.y+utils.stringToFloat(destination[2]))+" z="+(guideLoc.z+utils.stringToFloat(destination[3]))+
                " return_x="+(guideLoc.x+utils.stringToFloat(entrance[1]))+
                " return_y="+(guideLoc.y+utils.stringToFloat(entrance[2]))+" return_z="+(guideLoc.z+utils.stringToFloat(entrance[3]));
    }
    public String rryattCombatSetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattCombatSetup"));
        if(!kashyyykActor(p) || !space_dungeon.isCurrentRryattTrailController(p) ||
           hasObjVar(p,"capacity.transferProtection.operation")) return "protocol_bot=invalid-setup";
        location root=getLocation(getObjIdObjVar(p,space_dungeon.INSTANCE_ID));
        // Same authored entrance-relative clone floor in each translated set.
        float x=root.x+2.1f,y=root.y+1.0f,z=root.z+24.4f;
        boolean accepted=warpPlayerToInstance(p,"kashyyyk_rryatt_trail",getZoneInstanceId(p),x,y,z,null,x,y,z,"",true);
        return "protocol_bot=rryatt-combat-position accepted="+accepted;
    }
    public String rryattEnemySetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattEnemySetup"));
        if(!kashyyykActor(p,true) || !space_dungeon.isCurrentRryattTrailController(p) || !isOnAFloor(p))
            return "protocol_bot=invalid-setup";
        obj_id old=utils.getObjIdScriptVar(p,"fixture.rryatt.enemy");
        if(isIdValid(old) && exists(old)) return "protocol_bot=existing-enemy";
        if(!hasScript(p,"fixture.protocol_bot")) attachScript(p,"fixture.protocol_bot");
        int serial=utils.getIntScriptVar(p,"fixture.rryatt.enemy.serial");
        if(serial==Integer.MAX_VALUE || utils.hasScriptVar(p,"fixture.rryatt.enemy.pending")) return "protocol_bot=invalid-request";
        serial++;utils.setScriptVar(p,"fixture.rryatt.enemy.serial",serial);
        utils.setScriptVar(p,"fixture.rryatt.enemy.pending",serial);
        dictionary request=new dictionary();request.put("serial",serial);
        request.put("identity",p+":"+Integer.toUnsignedLong(getPlayerStationId(p))+":"+getPlayerFullName(p));
        request.put("controller",getObjIdObjVar(p,space_dungeon.INSTANCE_ID));
        boolean accepted=messageTo(p,"fixtureRryattEnemyCreate",request,0.1f,false);
        if(!accepted) utils.removeScriptVar(p,"fixture.rryatt.enemy.pending");
        return "protocol_bot=rryatt-enemy accepted="+accepted+" scheduled=true serial="+serial;
    }
    public int fixtureRryattEnemyCreate(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=player(identity(request.getString("identity"),""));int serial=request.getInt("serial");
        if(p==null || !p.equals(self) || serial<=0 || serial!=utils.getIntScriptVar(p,"fixture.rryatt.enemy.pending")) return SCRIPT_CONTINUE;
        // Consume the matching request before invoking the original factory.
        utils.removeScriptVar(p,"fixture.rryatt.enemy.pending");
        if(!kashyyykActor(p,true) || !space_dungeon.isCurrentRryattTrailController(p) || !isOnAFloor(p) ||
           !request.getObjId("controller").equals(getObjIdObjVar(p,space_dungeon.INSTANCE_ID))) return SCRIPT_CONTINUE;
        obj_id old=utils.getObjIdScriptVar(p,"fixture.rryatt.enemy");
        if(isIdValid(old) && exists(old)) return SCRIPT_CONTINUE;
        location point=getLocation(p);point.x+=2.0f;point.y=getFloorHeightAtRelativePointOnSameFloorAsObject(p,2.0f,0.0f);
        if(Float.isNaN(point.y) || Float.isInfinite(point.y)) return SCRIPT_CONTINUE;
        obj_id enemy=create.object("npe_droid_4warning_weak",point,2);
        if(!isIdValid(enemy)) return SCRIPT_CONTINUE;
        setObjVar(enemy,"fixture.rryatt.owner",p);
        // Explicit fixture health budget permits repeated real hits in one run.
        setMaxAttrib(enemy,HEALTH,100000);setAttrib(enemy,HEALTH,100000);
        setMaxAttrib(enemy,ACTION,100000);setAttrib(enemy,ACTION,100000);
        setMaxAttrib(enemy,MIND,100000);setAttrib(enemy,MIND,100000);
        attachScript(enemy,"fixture.protocol_bot");
        dictionary expiry=new dictionary();expiry.put("owner",p);expiry.put("enemy",enemy);
        messageTo(enemy,"fixtureRryattEnemyExpiry",expiry,300.0f,false);
        utils.setScriptVar(p,"fixture.rryatt.enemy",enemy);
        return SCRIPT_CONTINUE;
    }
    public int fixtureRryattEnemyExpiry(obj_id self,dictionary params) throws InterruptedException {
        if(identity("1:1:Capabcdefghijkl","")==null || isPlayer(self) || !self.equals(params.getObjId("enemy")) ||
           !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) || getCurrentZoneInstanceId()<0 ||
           !params.getObjId("owner").equals(getObjIdObjVar(self,"fixture.rryatt.owner"))) return SCRIPT_CONTINUE;
        stopCombat(self);
        // End this owned test creature through the ordinary death path before
        // removing its corpse; never clear a player combat flag for a test.
        if(!isDead(self)) kill(self);
        boolean removed=destroyObject(self);
        if(!removed) {
            int attempt=params.getInt("attempt");
            if(attempt<5) {params.put("attempt",attempt+1);messageTo(self,"fixtureRryattEnemyExpiry",params,1.0f,false);}
            else setObjVar(self,"fixture.rryatt.cleanup_failed",true);
        }
        return SCRIPT_CONTINUE;
    }
    public String rryattEnemyCleanup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattEnemyCleanup"));if(!isIdValid(p)) return "protocol_bot=invalid-setup";
        int removed=0;
        if("kashyyyk_rryatt_trail".equals(getCurrentSceneName()) && getCurrentZoneInstanceId()>=0) {
            obj_id[] all=getAllObjectsWithScript(getLocation(p),16000.0f,"fixture.protocol_bot");
            if(all!=null && all.length>64) return "protocol_bot=invalid-enemy-count";
            if(all!=null) for(obj_id enemy:all) {
                if(!isIdValid(enemy) || isPlayer(enemy) || !p.equals(getObjIdObjVar(enemy,"fixture.rryatt.owner"))) continue;
                if(!enemy.isAuthoritative() || !"kashyyyk_rryatt_trail".equals(getLocation(enemy).area) || getZoneInstanceId(enemy)!=getZoneInstanceId(p))
                    return "protocol_bot=invalid-enemy";
                dictionary cleanup=new dictionary();cleanup.put("owner",p);cleanup.put("enemy",enemy);
                if(!messageTo(enemy,"fixtureRryattEnemyExpiry",cleanup,0.1f,false))
                    return "protocol_bot=rryatt-enemy-cleanup accepted=false target="+enemy;
                removed++;
            }
        }
        utils.removeScriptVar(p,"fixture.rryatt.enemy.pending");
        utils.removeScriptVar(p,"fixture.rryatt.enemy");
        return "protocol_bot=rryatt-enemy-cleanup accepted=true scheduled="+removed;
    }
    public String rryattQuestReset(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattQuestReset"));
        if(!kashyyykActor(p) || !space_dungeon.isCurrentRryattTrailController(p)) return "protocol_bot=invalid-setup";
        groundquests.clearQuest(p,"ep3_rryatt_trail_mastery");
        grantSkill(p,"social_language_wookiee_comprehend");
        return "protocol_bot=rryatt-quest-reset accepted=true";
    }
    public String rryattMaster(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattMaster"));
        if(!kashyyykActor(p) || !space_dungeon.isCurrentRryattTrailController(p)) return "protocol_bot=invalid-setup";
        obj_id controller=getObjIdObjVar(p,space_dungeon.INSTANCE_ID),found=null;
        int anchor=locations.getBuildoutAreaRow(controller);
        obj_id[] npcs=getAllObjectsWithScript(getLocation(controller),4000.0f,"conversation.ep3_achonnko");
        if(npcs!=null) for(obj_id n:npcs) if(isIdValid(n) && n.isAuthoritative() &&
                getZoneInstanceId(n)==getZoneInstanceId(p) && locations.getBuildoutAreaRow(n)==anchor) {
            if(found!=null) return "protocol_bot=ambiguous-master";
            found=n;
        }
        if(!isIdValid(found)) return "protocol_bot=no-authored-master";
        location l=getLocation(found);
        obj_id spawner=utils.getObjIdScriptVar(found,"spawnedBy");
        if(!isIdValid(spawner) || !exists(spawner)) return "protocol_bot=missing-master-spawner";
        location authored=getLocation(spawner);
        if(Math.abs(authored.x-l.x)>.1f || Math.abs(authored.z-l.z)>.1f || Math.abs(authored.y-l.y)>3)
            return "protocol_bot=invalid-master-position target="+found+" y="+l.y+" authored_y="+authored.y;
        obj_id previous=utils.getObjIdScriptVar(p,"fixture.rryatt.guide");
        int attempt=found.equals(previous)?utils.getIntScriptVar(p,"fixture.rryatt.masterApproach"):0;
        if(attempt>=16) return "protocol_bot=no-master-approach";
        vector point=rryattApproach(found,attempt);float y=point.y;
        utils.setScriptVar(p,"fixture.rryatt.guide",found);
        utils.setScriptVar(p,"fixture.rryatt.masterApproach",attempt+1);
        String routes="";String[] keys={"trailMasteryTwo","trailMasteryThree","trailMasteryFour","trailMasteryFive"};
        for(String key:keys) {
            String route=getStringObjVar(found,key);
            String[] d=split(dataTableGetString("datatables/travel/zone_transition.iff",route,"destination"),':');
            if(d.length!=4 || !"offset".equals(d[0])) return "protocol_bot=invalid-master-route";
            routes+=(routes.length()==0?"":",")+route+":"+(l.x+Float.parseFloat(d[1]))+":"+(l.y+Float.parseFloat(d[2]))+":"+(l.z+Float.parseFloat(d[3]));
        }
        boolean accepted=warpPlayerToInstance(p,l.area,getZoneInstanceId(p),point.x,y,point.z,null,point.x,y,point.z,"",true);
        return "protocol_bot=rryatt-master-setup accepted="+accepted+" target="+found+" anchor="+anchor+" routes="+routes;
    }
    private String cloneMappingSources(obj_id p) throws InterruptedException {
        String table="datatables/cloning/clone_mapping.iff",seen="|",result="";
        location point=getLocation(p);int count=dataTableGetNumRows(table);
        if(point==null || count<1 || count>512)return "invalid";
        for(int row=0;row<count;row++) {
            if(!point.area.equals(dataTableGetString(table,row,"scene")))continue;
            String scene=dataTableGetString(table,row,"clone_scene");
            if(scene==null || scene.length()==0 || seen.indexOf("|"+scene+"|")>=0)continue;
            seen+=scene+"|";
            obj_id planet=getPlanetByName(scene);
            java.util.Vector facilities=isIdValid(planet)?utils.getResizeableObjIdArrayScriptVar(planet,cloninglib.VAR_PLANET_CLONE_ID):null;
            result+=(result.length()==0?"":",")+scene+":"+planet+":"+(facilities==null?-1:facilities.size());
        }
        return result.length()==0?"none":result;
    }
    private String fixtureActionResult(obj_id p,String action,boolean accepted) throws InterruptedException {
        int serial=utils.getIntScriptVar(p,"fixture.completed.serial");
        if(serial==Integer.MAX_VALUE) return "protocol_bot=invalid-setup-serial";
        utils.setScriptVar(p,"fixture.completed.action",action);
        utils.setScriptVar(p,"fixture.completed.accepted",Boolean.toString(accepted));
        utils.setScriptVar(p,"fixture.completed.serial",serial+1);
        return "protocol_bot=rryatt-setup accepted="+accepted+" serial="+(serial+1);
    }
    public String rryattDeath(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattDeath"));
        if(!kashyyykActor(p) || !space_dungeon.isCurrentRryattTrailController(p) || isDead(p)) return "protocol_bot=invalid-setup";
        if(!hasScript(p,"fixture.protocol_bot")) attachScript(p,"fixture.protocol_bot");
        dictionary request=new dictionary();request.put("identity",p+":"+Integer.toUnsignedLong(getPlayerStationId(p))+":"+getPlayerFullName(p));
        boolean started=messageTo(p,"fixtureDeath",request,1.0f,false);
        return fixtureActionResult(p,"botRryattDeath",started);
    }
    public int fixtureDeath(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=player(identity(request.getString("identity"),""));
        if(p==null || !p.equals(self) || !kashyyykActor(p) ||
                !space_dungeon.isCurrentRryattTrailController(p) || isDead(p)) return SCRIPT_CONTINUE;
        setObjVar(p,pclib.VAR_BEEN_COUPDEGRACED,true);
        setInvulnerable(p,false);
        messageTo(p,"fixtureDeathNotify",request,1.0f,false);
        kill(p);
        return SCRIPT_CONTINUE;
    }
    public int fixtureDeathNotify(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=player(identity(request.getString("identity"),""));
        if(p==null || !p.equals(self) || !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) ||
                !space_dungeon.isCurrentRryattTrailController(p) || !isDead(p)) return SCRIPT_CONTINUE;
        pclib.playerDeath(p,p,false);
        return SCRIPT_CONTINUE;
    }
    public String rryattResurrect(String value) throws InterruptedException {
        obj_id p=player(identity(value,"rryattResurrect"));
        if(!isIdValid(p) || getCurrentZoneInstanceId()!=0 || getState(p,STATE_COMBAT)!=0 ||
                hasObjVar(p,"capacity.groupTransfer.id") || hasObjVar(p,"hasOutstandingRequestSceneTransfer") ||
                !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) || !isDead(p)) return "protocol_bot=invalid-setup";
        if(!hasScript(p,"fixture.protocol_bot")) attachScript(p,"fixture.protocol_bot");
        dictionary request=new dictionary();request.put("identity",p+":"+Integer.toUnsignedLong(getPlayerStationId(p))+":"+getPlayerFullName(p));
        boolean accepted=messageTo(p,"fixtureResurrect",request,1.0f,false);
        return fixtureActionResult(p,"botRryattResurrect",accepted);
    }
    public int fixtureResurrect(obj_id self,dictionary request) throws InterruptedException {
        obj_id p=player(identity(request.getString("identity"),""));
        if(p==null || !p.equals(self) || !"kashyyyk_rryatt_trail".equals(getCurrentSceneName()) || !isDead(p)) return SCRIPT_CONTINUE;
        pclib.resurrectPlayer(p);
        return SCRIPT_CONTINUE;
    }
    private String rryattReferences(String value,int mode) throws InterruptedException {
        String[] names={"rryattLegacy","rryattStale","rryattForeignGuide"};
        obj_id p=player(identity(value,names[mode]));
        if(!kashyyykActor(p) || !space_dungeon.isCurrentRryattTrailController(p)) return "protocol_bot=invalid-setup";
        int anchor=locations.getBuildoutAreaRow(getObjIdObjVar(p,space_dungeon.INSTANCE_ID));
        if(mode==0) removeObjVar(p,space_dungeon.INSTANCE_ID);
        if(mode==1) setObjVar(p,space_dungeon.INSTANCE_ID,obj_id.getObjId(9223372036854775806L));
        if(mode==2) {
            obj_id found=null;
            obj_id[] guides=getAllObjectsWithScript(getLocation(p),16000.0f,"conversation.rryatt_trail_guide");
            if(guides!=null) for(obj_id n:guides) if(isIdValid(n) && n.isAuthoritative() &&
                    getZoneInstanceId(n)==getZoneInstanceId(p) && locations.getBuildoutAreaRow(n)==(anchor+4)%24) {found=n;break;}
            // A managed world contains only one authored set. Reproduce an
            // unloaded prior world's cached guide without creating any object.
            if(!isIdValid(found) && getCurrentZoneInstanceId()>0 &&
                    "true".equals(getConfigSetting("GameServer","capacityRryattInstancesEnabled")))
                found=obj_id.getObjId(9223372036854775806L);
            if(!isIdValid(found)) return "protocol_bot=no-foreign-guide";
            setObjVar(p,"lastRryattTransition",found);
        }
        return "protocol_bot=rryatt-reference-setup accepted=true anchor="+anchor;
    }
    public String rryattLegacy(String value) throws InterruptedException {return rryattReferences(value,0);}
    public String rryattStale(String value) throws InterruptedException {return rryattReferences(value,1);}
    public String rryattForeignGuide(String value) throws InterruptedException {return rryattReferences(value,2);}
    public String rryattGuide0(String value) throws InterruptedException { return rryattGuide(value,0); }
    public String rryattGuide1(String value) throws InterruptedException { return rryattGuide(value,1); }
    public String rryattGuide2(String value) throws InterruptedException { return rryattGuide(value,2); }
    public String rryattGuide3(String value) throws InterruptedException { return rryattGuide(value,3); }
    public String rryattGuide4(String value) throws InterruptedException { return rryattGuide(value,4); }
    public String rryattGuide5(String value) throws InterruptedException { return rryattGuide(value,5); }
    public String rryattGuide6(String value) throws InterruptedException { return rryattGuide(value,6); }
    public String rryattGuide7(String value) throws InterruptedException { return rryattGuide(value,7); }
    public String kashyyykHome(String value) throws InterruptedException {
        obj_id p=player(identity(value,"kashyyykHome"));
        if(!kashyyykActor(p) || !"kashyyyk_main".equals(getCurrentSceneName()) ||
                !"WGC_AE80ACB41011".equals(getConfigSetting("dbProcess","schemaOwner"))) return "protocol_bot=invalid-setup";
        return "protocol_bot=kashyyyk-home-setup accepted="+fixtureStationTravel(p);
    }
    private obj_id launchTerminal(obj_id p) throws InterruptedException {
        obj_id root=getTopMostContainer(p), found=null;
        obj_id[] all=getAllObjectsWithScript(getWorldLocation(p),1000.0f,"npe.ord_mantell_terminal");
        if(all!=null) for(obj_id t:all) if(isIdValid(t) && t.isAuthoritative() && root.equals(getTopMostContainer(t))) {
            if(found!=null) return null;
            found=t;
        }
        return found;
    }
    public String splitStation(String value) throws InterruptedException {
        obj_id p=player(identity(value,"splitStation"));
        if(!isIdValid(p) || !isPlayerConnected(p) || isIdValid(getGroupObject(p)) ||
                getState(p,STATE_COMBAT)!=0 || hasObjVar(p,"capacity.groupTransfer.id") ||
                hasObjVar(p,"hasOutstandingRequestSceneTransfer") ||
                !"dungeon1".equals(getCurrentSceneName()) || getCurrentZoneInstanceId()!=0 ||
                !"npe_space_station".equals(getStringObjVar(getTopMostContainer(p),"instance_name")))
            return "protocol_bot=invalid-setup";
        obj_id source=getTopMostContainer(p), destination=null;
        obj_id[] roots=getAllObjectsWithScript(new location(0,0,0,"dungeon1"),1000000.0f,"npe.npe_public_instance");
        if(roots==null || roots.length>100) return "protocol_bot=invalid-station-count";
        for(obj_id root:roots) if(isIdValid(root) && root.isAuthoritative() && !source.equals(root) &&
                "npe_space_station".equals(getStringObjVar(root,"instance_name")) &&
                (destination==null || root.toString().compareTo(destination.toString())<0)) destination=root;
        location l=getLocation(p);
        String room=getCellName(l.cell);
        if(!isIdValid(destination) || room==null || !isIdValid(getCellId(destination,room)))
            return "protocol_bot=no-matching-room";
        // Recorded setup of dedicated bots only. Consolidation itself must use
        // the ordinary group commands and preserve this matching room/point.
        vector world=getTransform_o2w(getCellId(destination,room)).rotateTranslate_l2p(new vector(l.x,l.y,l.z));
        boolean accepted=warpPlayerToInstance(p,"dungeon1",0L,world.x,world.y,world.z,
                destination,room,l.x,l.y,l.z,"",true);
        return "protocol_bot=split-setup accepted="+accepted+" source="+source+" destination="+destination;
    }
    public String friendSetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"friendSetup"));
        if(!isIdValid(p) || !isPlayerConnected(p) || getState(p,STATE_COMBAT)!=0 ||
                hasObjVar(p,"capacity.groupTransfer.id") || hasObjVar(p,"hasOutstandingRequestSceneTransfer"))
            return "protocol_bot=invalid-setup";
        obj_id root=getTopMostContainer(p), found=null;
        obj_id[] all=getAllObjectsWithScript(getWorldLocation(p),1000.0f,"npe.npe_instance_transfer_terminal");
        if(all!=null) for(obj_id t:all) if(isIdValid(t) && t.isAuthoritative() && root.equals(getTopMostContainer(t))) {
            if(found!=null) return "protocol_bot=ambiguous-terminal";
            found=t;
        }
        if(!isIdValid(found)) return "protocol_bot=no-friend-terminal";
        location l=getLocation(found);
        vector world=getTransform_o2w(l.cell).rotateTranslate_l2p(new vector(l.x+1.0f,l.y,l.z));
        boolean accepted=warpPlayerToInstance(p,getCurrentSceneName(),getCurrentZoneInstanceId(),world.x,world.y,world.z,
                root,getCellName(l.cell),l.x+1.0f,l.y,l.z,"",true);
        return "protocol_bot=friend-setup accepted="+accepted+" target="+found;
    }
    public String pilotSetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"pilotSetup"));
        if(!isIdValid(p) || !isPlayerConnected(p) || getState(p,STATE_COMBAT)!=0 ||
                hasObjVar(p,"capacity.groupTransfer.id") || hasObjVar(p,"hasOutstandingRequestSceneTransfer") ||
                !"npe_space_station".equals(getStringObjVar(getTopMostContainer(p),"instance_name"))) return "protocol_bot=invalid-setup";
        obj_id t=launchTerminal(p);
        if(!isIdValid(t)) return "protocol_bot=no-launch-terminal";
        // Explicit fixture reward setup, using the same ship grant as Serissu.
        // This does not count as training-conversation or launch acceptance.
        if(!space_utils.hasShip(p)) space_quest.grantNewbieShip(p,"neutral");
        obj_id[] devices=space_transition.findShipControlDevicesForPlayer(p);
        if(devices==null || devices.length!=1) return "protocol_bot=invalid-ship-count";
        obj_id ship=space_transition.getShipFromShipControlDevice(devices[0]);
        if(!isIdValid(ship) || !p.equals(getOwner(ship)) || !space_utils.isShipUsable(ship,p)) return "protocol_bot=invalid-owned-ship";
        location l=getLocation(t);
        vector world=getTransform_o2w(l.cell).rotateTranslate_l2p(new vector(l.x+1.0f,l.y,l.z));
        boolean accepted=warpPlayerToInstance(p,getCurrentSceneName(),getCurrentZoneInstanceId(),world.x,world.y,world.z,
                getTopMostContainer(t),getCellName(l.cell),l.x+1.0f,l.y,l.z,"",true);
        return "protocol_bot=pilot-setup accepted="+accepted+" target="+t+" ship="+ship+" device="+devices[0];
    }
    public String landingSetup(String value) throws InterruptedException {
        obj_id p=player(identity(value,"landingSetup"));
        if(!isIdValid(p) || !isPlayerConnected(p) || !"space_ord_mantell".equals(getCurrentSceneName()) ||
                getState(p,STATE_COMBAT)!=0 || hasObjVar(p,"capacity.groupTransfer.id") ||
                hasObjVar(p,"hasOutstandingRequestSceneTransfer")) return "protocol_bot=invalid-setup";
        obj_id ship=space_transition.getContainingShip(p), found=null;
        if(!isIdValid(ship) || !p.equals(getOwner(ship)) || !p.equals(getPilotId(ship))) return "protocol_bot=invalid-pilot";
        obj_id[] all=getAllObjectsWithScript(getLocation(ship),32000.0f,"conversation.station_ord_mantell");
        if(all!=null) for(obj_id t:all) if(isIdValid(t) && t.isAuthoritative()) {
            if(found!=null) return "protocol_bot=ambiguous-station";
            found=t;
        }
        if(!isIdValid(found)) return "protocol_bot=no-space-station";
        // Bounded positioning setup only; the peer must request real comm landing.
        location l=getLocation(found);l.x+=250.0f;
        boolean accepted=setLocation(ship,l);
        return "protocol_bot=landing-setup accepted="+accepted+" target="+found+" ship="+ship;
    }
    public String station(String value) throws InterruptedException {
        obj_id p=player(identity(value,"station"));
        if(!isIdValid(p) || !isPlayerConnected(p) || !"tutorial".equals(getCurrentSceneName()) ||
                isIdValid(getGroupObject(p)) || getState(p,STATE_COMBAT)!=0 ||
                hasObjVar(p,"hasOutstandingRequestSceneTransfer")) return "protocol_bot=invalid-setup";
        // Explicit setup into this retained fixture's authored Tansaari copy.
        // This is not terminal acceptance; later travel must use real menus/SUI.
        if(!"WGC_AE80ACB41011".equals(getConfigSetting("dbProcess","schemaOwner"))) return "protocol_bot=invalid-setup";
        return "protocol_bot=station-request accepted="+fixtureStationTravel(p);
    }
    private boolean fixtureStationTravel(obj_id p) throws InterruptedException {
        dictionary entrance=npe.getNpeInstanceInfo(npe.DUNGEON_SPACE_STATION);
        location local=entrance.getLocation("cell_loc");
        String room=entrance.getString("cell");
        if(local==null || !"hangarbay2".equals(room)) return false;
        setObjVar(p,npe.VAR_NPE_PHASE,3);
        attachScript(p,npe.SCRIPT_PUBLIC_TRAVEL);
        attachScript(p,"npe.trigger_journal");
        if(Boolean.parseBoolean(getConfigSetting("GameServer","capacityHostedPublicInstancesEnabled"))) {
            if(!npe.preparePublicStationTravel(p))return false;
            return npe.requestPublicStationTravel(p,npe.DUNGEON_SPACE_STATION);
        }
        return warpPlayerToInstance(p,"dungeon1",0L,0.0f,0.0f,0.0f,
                obj_id.getObjId(-535083930726957057L),room,local.x,local.y,local.z,"msgNpeInstanceTravelComplete",true);
    }
    private obj_id terminal(obj_id p) throws InterruptedException {
        obj_id building=getTopMostContainer(p);
        if(!isIdValid(building) || !hasScript(building,"npe.npe_public_instance")) return null;
        obj_id[] terminals=getAllObjectsWithScript(getWorldLocation(p),1000.0f,"npe.gamma_shuttle");
        obj_id found=null;
        if(terminals!=null) for(obj_id t:terminals) {
            if(isIdValid(t) && t.isAuthoritative() && building.equals(getTopMostContainer(t))) {
                if(found!=null) return null;
                found=t;
            }
        }
        return found;
    }
    public String terminals(String value) throws InterruptedException {
        obj_id p=player(identity(value,"terminals"));
        if(!isIdValid(p)) return "protocol_bot=absent";
        obj_id t=terminal(p);
        if(!isIdValid(t)) return "protocol_bot=no-terminal";
        location l=getLocation(t);
        return "protocol_bot=terminal target="+t+" cell="+l.cell+" x="+l.x+" y="+l.y+" z="+l.z+
                " selector=gamma_shuttle terminal_metadata=2 scene="+l.area+" family="+fixtureFamily(p)+
                " same_cell="+l.cell.equals(getLocation(p).cell)+" distance="+getDistance(p,t);
    }
    public String prepare(String value) throws InterruptedException {
        obj_id p=player(identity(value,"prepare"));
        if(!isIdValid(p) || !isPlayerConnected(p) || getState(p,STATE_COMBAT)!=0 ||
                isIdValid(getGroupObject(p)) || hasObjVar(p,"capacity.groupTransfer.id")) return "protocol_bot=invalid-setup";
        obj_id t=terminal(p);
        if(!isIdValid(t)) return "protocol_bot=no-terminal";
        // A staged character needs the station's ordinary SUI callback script.
        if(getIntObjVar(p,npe.VAR_NPE_PHASE)!=3) return "protocol_bot=invalid-phase";
        attachScript(p,"npe.trigger_journal");
        location l=getLocation(t);
        obj_id building=getTopMostContainer(t);
        String room=getCellName(l.cell);
        if(room==null || room.length()==0 || !building.equals(getTopMostContainer(p))) return "protocol_bot=invalid-room";
        vector world=getTransform_o2w(l.cell).rotateTranslate_l2p(new vector(l.x+1.0f,l.y,l.z));
        boolean accepted=warpPlayerToInstance(p,getCurrentSceneName(),getCurrentZoneInstanceId(),
                world.x,world.y,world.z,building,room,l.x+1.0f,l.y,l.z,"",true);
        return "protocol_bot=prepared target="+t+" accepted="+accepted;
    }
}
