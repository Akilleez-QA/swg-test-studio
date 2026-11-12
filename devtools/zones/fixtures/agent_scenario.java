package script.fixture;
import script.*;
import script.library.*;

/**
 * Scenario family of the agent fixture: the world around one registered
 * fixture bot, and its teardown. Creates objects and creatures, controls
 * fixture-spawned creatures, sets quest state and test objvars, warps the
 * bot to another scene and turns it. See docs/fixture-scenario.md.
 *
 * Invoked through the CentralServer console:
 *   game <serverId> runScript fixture.agent_scenario <method> <oid>:<stationId>:<characterName> [typed args...]
 *
 * The isolation and identity guard and its helpers are copied verbatim
 * from agent_fixture.java (a test checks they stay identical). Every
 * object or creature an op creates carries the objvars fixture.scenario
 * (the scenario id) and fixture.owner (the bot). Creating ops take the
 * scenario id as their first argument and refuse unless it is the id the
 * bot has open (objvar fixture.scenario_open, set by scenarioBegin).
 * scenarioEnd destroys what is tagged with the id and still reachable.
 *
 * No free-form command, script name, class name or expression; no god or
 * admin grant; no player or creature-player template; never another
 * player. One top-level type only, so it deploys as a single file.
 */
public class agent_scenario extends base_script {
    private static final String P="agent_scenario=";
    private static final int MAX_ROWS=200;
    private static final float SCOPE_RANGE=256.0f;
    private static final int CHAIN_MAX=64;
    private static final String OID_RE="[1-9][0-9]{0,18}";
    private static final String NUM_RE="-?[0-9]{1,5}(\\.[0-9]{1,6})?";
    private static final String INT_RE="-?[0-9]{1,9}";
    private static final String CELL_RE="[A-Za-z0-9_]{1,64}";

    // Scenario tagging (sources/interface.md; owner: this family).
    private static final String SCENARIO_RE="[a-z][a-z0-9_]{0,31}";
    private static final String TAG_SCENARIO="fixture.scenario";
    private static final String TAG_OWNER="fixture.owner";
    private static final String OPEN_VAR="fixture.scenario_open";
    private static final String CREATED_VAR="fixture.scenario_created";
    private static final String TEST_VAR_ROOT="fixture.t";
    private static final int SCENARIO_CREATE_MAX=200;
    private static final int SCENARIO_END_MAX=1000;

    // Typed arguments (the same regexes and bounds as swg_test_studio/fixture_ops/scenario.py).
    private static final String TEMPLATE_RE="object/(tangible|weapon|static)/([a-z0-9_]{1,64}/){0,7}[a-z0-9_]{1,64}\\.iff";
    private static final int TEMPLATE_MAX=200;
    private static final String CREATURE_RE="[a-z0-9_]{1,64}";
    private static final String QUEST_RE="[a-z0-9_]{1,64}(/[a-z0-9_]{1,64}){0,3}";
    private static final String SIGNAL_RE="[A-Za-z0-9_]{1,64}";
    private static final String TARGET_RE="self|[1-9][0-9]{0,18}";
    private static final String VAR_NAME_RE="[a-z0-9_]{1,32}(\\.[a-z0-9_]{1,32}){0,3}";
    private static final String VAR_TYPE_RE="int|float|string";
    private static final String VAR_VALUE_RE="[A-Za-z0-9_.:,/+-]{1,128}";
    private static final String ONOFF_RE="on|off";
    private static final float WORLD_XZ_MAX=8192.0f;
    private static final float WORLD_Y_MIN=-1000.0f;
    private static final float WORLD_Y_MAX=10000.0f;
    private static final float CELL_LOCAL_MAX=512.0f;
    private static final float SPAWN_OFFSET_MAX=64.0f;
    private static final float YAW_MAX=360.0f;
    private static final int SPAWN_LEVEL_MIN=1;
    private static final int SPAWN_LEVEL_MAX=90;
    private static final int INVENTORY_COUNT_MAX=10;
    private static final int VAR_INT_MAX=999999999;
    private static final float VAR_FLOAT_MAX=100000.0f;
    // Ground scenes a bot may be warped to: the open-world planets of the
    // server tree's datatables/region/planets.tab. Tutorial, instanced
    // dungeon, adventure and Kashyyyk sub-zone scenes are left out.
    private static final String[] SCENES={
        "corellia","dantooine","dathomir","endor","kashyyyk_main","lok",
        "mustafar","naboo","rori","talus","tatooine","yavin4"
    };

    // ------------------------------------------------------------------
    // Guard (verbatim copy of agent_fixture.java)
    // ------------------------------------------------------------------

    /**
     * Environment + identity guard (the protocol_bot identity()/player()
     * pattern) followed by an argument-count check. Returns
     * {error-or-null, bot, args}. Arguments are then parsed by the typed
     * parsers below.
     */
    private Object[] request(String value,String method,int minArgs,int maxArgs) throws InterruptedException {
        String schema=getConfigSetting("dbProcess","schemaOwner");
        if(!"1".equals(getConfigSetting("GameServer","clientIsolationFixture")) ||
                schema==null || !schema.matches("WGC_[A-F0-9]{12}")) return refusal("invalid-scope");
        if(value==null || value.length()>4096) return refusal("invalid-args");
        value=value.trim();
        if(value.startsWith(method+" ")) value=value.substring(method.length()+1).trim();
        String[] tokens=value.split("\\s+");
        String[] fields=tokens[0].split(":",-1);
        if(fields.length!=3 || !fields[0].matches("[1-9][0-9]{0,18}") ||
                !fields[1].matches("[1-9][0-9]{0,9}") || !fields[2].matches("Cap[a-z]{12}")) return refusal("invalid-scope");
        long id,station;
        try {id=Long.parseLong(fields[0]);station=Long.parseLong(fields[1]);}
        catch(NumberFormatException e) {return refusal("invalid-scope");}
        obj_id p=obj_id.getObjId(id);
        if(!isIdValid(p) || !p.isAuthoritative() || !exists(p)) return refusal("not-here");
        if(!isPlayer(p) || !fields[2].equals(getPlayerFullName(p)) ||
                Integer.toUnsignedLong(getPlayerStationId(p))!=station || isGod(p)) return refusal("invalid-identity");
        int n=tokens.length-1;
        if(n<minArgs || n>maxArgs) return refusal("invalid-args reason=arg-count");
        String[] args=new String[n];
        System.arraycopy(tokens,1,args,0,n);
        return new Object[]{null,p,args};
    }
    private static Object[] refusal(String status) {return new Object[]{status,null,null};}

    private static Float num(String s,float lo,float hi) {
        if(s==null || !s.matches(NUM_RE)) return null;
        float v;
        try {v=Float.parseFloat(s);} catch(NumberFormatException e) {return null;}
        if(Float.isNaN(v) || v<lo || v>hi) return null;
        return v;
    }
    private static Integer integer(String s,int lo,int hi) {
        if(s==null || !s.matches(INT_RE)) return null;
        int v;
        try {v=Integer.parseInt(s);} catch(NumberFormatException e) {return null;}
        if(v<lo || v>hi) return null;
        return v;
    }
    private static obj_id oid(String s) {
        if(s==null || !s.matches(OID_RE)) return null;
        long v;
        try {v=Long.parseLong(s);} catch(NumberFormatException e) {return null;}
        obj_id o=obj_id.getObjId(v);
        return isIdValid(o)?o:null;
    }
    /** Comma list of 1..max entries, each matching re; null on any violation. */
    private static String[] list(String s,String re,int max) {
        if(s==null || s.length()==0 || s.length()>2048) return null;
        String[] parts=s.split(",",-1);
        if(parts.length<1 || parts.length>max) return null;
        for(String part:parts) if(!part.matches(re)) return null;
        return parts;
    }

    /** The building the bot stands in, or null outdoors. */
    private static obj_id botBuilding(obj_id bot) throws InterruptedException {
        location l=getLocation(bot);
        if(l==null || !isIdValid(l.cell)) return null;
        obj_id top=getTopMostContainer(bot);
        return isIdValid(top) && !top.equals(bot)?top:null;
    }

    /**
     * Null when the bot may act on o, else a status. In scope: the object is
     * loaded and authoritative here, and is (recursively) contained by the
     * bot, or by the building the bot stands in, or is in the bot's scene
     * within SCOPE_RANGE of the bot. Never another player, nor anything
     * contained by another player. The bot itself only when allowBot.
     */
    private static String scope(obj_id bot,obj_id o,boolean allowBot) throws InterruptedException {
        if(!isIdValid(o) || !exists(o) || !o.isAuthoritative()) return "out-of-scope reason=not-loaded object="+o;
        if(o.equals(bot)) return allowBot?null:"out-of-scope reason=self object="+o;
        obj_id building=botBuilding(bot);
        boolean contained=false;
        obj_id c=o;
        for(int i=0;i<CHAIN_MAX && isIdValid(c);i++) {
            if(c.equals(bot)) {contained=true;break;}
            if(isPlayer(c)) return "out-of-scope reason=other-player object="+o;
            if(building!=null && c.equals(building)) {contained=true;break;}
            c=getContainedBy(c);
        }
        if(contained) return null;
        location w=getWorldLocation(o),b=getWorldLocation(bot);
        if(w==null || b==null || w.area==null || !w.area.equals(b.area) ||
                !w.area.equals(getCurrentSceneName())) return "out-of-scope reason=scene object="+o;
        if(getDistance(w,b)>SCOPE_RANGE) return "out-of-scope reason=distance object="+o;
        return null;
    }

    /** Percent-encodes everything outside [A-Za-z0-9._~/:-]; commas and spaces included. */
    private static String enc(Object value) {
        String s=String.valueOf(value);
        StringBuilder b=new StringBuilder(s.length());
        byte[] bytes=s.getBytes(java.nio.charset.StandardCharsets.UTF_8);
        for(byte x:bytes) {
            int ch=x&0xff;
            if((ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||(ch>='0'&&ch<='9')||ch=='.'||ch=='_'||ch=='~'||ch=='/'||ch==':'||ch=='-')
                b.append((char)ch);
            else b.append('%').append(Character.toUpperCase(Character.forDigit(ch>>4,16))).append(Character.toUpperCase(Character.forDigit(ch&15,16)));
        }
        return b.length()==0?"none":b.toString();
    }
    private static StringBuilder start(String status) {return new StringBuilder(P).append(status);}
    private static StringBuilder kv(StringBuilder sb,String key,Object value) {
        return sb.append(' ').append(key).append('=').append(enc(value));
    }
    /** Appends one row unless MAX_ROWS is reached; rc = {rows, truncated(0/1)}. */
    private static void row(StringBuilder sb,int[] rc,Object... parts) {
        if(rc[0]>=MAX_ROWS) {rc[1]=1;return;}
        sb.append(" row=");
        for(int i=0;i<parts.length;i++) sb.append(i==0?"":",").append(enc(parts[i]));
        rc[0]++;
    }
    private static String end(StringBuilder sb,int[] rc) {
        return sb.append(" rows=").append(rc[0]).append(" truncated=").append(rc[1]!=0).toString();
    }
    private static String fail(String status) {return P+status;}
    private static String invalidArgs(String why) {return P+"invalid-args reason="+enc(why);}

    // ------------------------------------------------------------------
    // Family helpers: typed parsers, tagging, created-object scope
    // ------------------------------------------------------------------

    private static String match(String s,String re) {return s!=null && s.matches(re)?s:null;}

    /** An object template of an allowed category, never a shared (client) template. */
    private static String template(String s) {
        if(s==null || s.length()>TEMPLATE_MAX || !s.matches(TEMPLATE_RE)) return null;
        if(s.contains("/shared_") || s.contains("/player/")) return null;
        return s;
    }

    private static String sceneName(String s) {
        if(s!=null) for(String scene:SCENES) if(scene.equals(s)) return s;
        return null;
    }

    /** The scenario id the bot has open, or null. */
    private static String openScenario(obj_id bot) throws InterruptedException {
        return hasObjVar(bot,OPEN_VAR)?getStringObjVar(bot,OPEN_VAR):null;
    }

    /** Null when the bot has scenario id open and its creation cap allows n more objects, else a status. */
    private static String mayCreate(obj_id bot,String id,int n) throws InterruptedException {
        if(!id.equals(openScenario(bot))) return "refused reason=scenario-not-open scenario="+id;
        int created=hasObjVar(bot,CREATED_VAR)?getIntObjVar(bot,CREATED_VAR):0;
        if(created+n>SCENARIO_CREATE_MAX) return "refused reason=scenario-cap cap="+SCENARIO_CREATE_MAX;
        return null;
    }

    /** Tags a freshly created object; destroys it when tagging fails. */
    private static boolean tag(obj_id bot,obj_id o,String id) throws InterruptedException {
        if(!isIdValid(o)) return false;
        if(!setObjVar(o,TAG_SCENARIO,id) || !setObjVar(o,TAG_OWNER,bot)) {destroyObject(o);return false;}
        int created=hasObjVar(bot,CREATED_VAR)?getIntObjVar(bot,CREATED_VAR):0;
        setObjVar(bot,CREATED_VAR,created+1);
        return true;
    }

    /** The scenario id o is tagged with for this bot, or null when o was not created for it. */
    private static String taggedFor(obj_id bot,obj_id o) throws InterruptedException {
        if(!isIdValid(o) || !exists(o) || isPlayer(o) || !hasObjVar(o,TAG_SCENARIO) || !hasObjVar(o,TAG_OWNER)) return null;
        obj_id owner=getObjIdObjVar(o,TAG_OWNER);
        return bot.equals(owner)?getStringObjVar(o,TAG_SCENARIO):null;
    }

    /** Null when o is an in-scope object the fixture created for this bot (a creature when mob), else a status. */
    private static String created(obj_id bot,obj_id o,boolean mob) throws InterruptedException {
        String s=scope(bot,o,false);
        if(s!=null) return s;
        if(taggedFor(bot,o)==null) return "out-of-scope reason=not-fixture-created object="+o;
        if(mob && !isMob(o)) return "out-of-scope reason=not-a-creature object="+o;
        return null;
    }

    /** A test objvar target: the bot itself ("self") or an object the fixture created for it. */
    private static Object[] varTarget(obj_id bot,String s) throws InterruptedException {
        if(match(s,TARGET_RE)==null) return new Object[]{invalidArgs("target"),null};
        if("self".equals(s)) return new Object[]{null,bot};
        obj_id o=oid(s);
        if(o==null) return new Object[]{invalidArgs("target"),null};
        String st=created(bot,o,false);
        return st!=null?new Object[]{fail(st),null}:new Object[]{null,o};
    }

    /** The bot's location moved by (dx,dz), in the bot's cell when indoors. */
    private static location near(obj_id bot,float dx,float dz) throws InterruptedException {
        location l=getLocation(bot);
        if(l==null) return null;
        location t=isIdValid(l.cell)?new location(l.x+dx,l.y,l.z+dz,l.area,l.cell):new location(l.x+dx,l.y,l.z+dz,l.area);
        if(!isIdValid(l.cell)) t.y=getHeightAtLocation(t.x,t.z);
        return t;
    }

    // ------------------------------------------------------------------
    // Scenario lifecycle
    // ------------------------------------------------------------------

    /** scenarioBegin <id>: records the open scenario on the bot. Re-opening the same id is a no-op. */
    public String scenarioBegin(String value) throws InterruptedException {
        Object[] q=request(value,"scenarioBegin",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE);
        if(id==null) return invalidArgs("scenario");
        String open=openScenario(bot);
        if(id.equals(open)) return P+"ok scenario="+id+" already=true";
        if(open!=null) return fail("refused reason=other-scenario-open open="+enc(open));
        boolean ok=setObjVar(bot,OPEN_VAR,id) && setObjVar(bot,CREATED_VAR,0);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"scenario",id);kv(sb,"already",false);kv(sb,"scene",getCurrentSceneName());kv(sb,"cap",SCENARIO_CREATE_MAX);
        return sb.toString();
    }

    /** Every object tagged with scenario id for this bot that this server can reach (bot, its building, its scene within reach). */
    private static java.util.List<obj_id> reachableTagged(obj_id bot,String id) throws InterruptedException {
        java.util.List<obj_id> found=new java.util.ArrayList<obj_id>();
        java.util.Set<String> seen=new java.util.HashSet<String>();
        java.util.List<obj_id[]> sources=new java.util.ArrayList<obj_id[]>();
        sources.add(utils.getContents(bot,true));
        obj_id building=botBuilding(bot);
        if(building!=null) sources.add(utils.getContents(building,true));
        sources.add(getObjectsInRange(bot,SCOPE_RANGE));
        for(obj_id[] batch:sources) {
            if(batch==null) continue;
            for(obj_id o:batch) {
                if(!isIdValid(o) || !seen.add(o.toString())) continue;
                if(id.equals(taggedFor(bot,o)) && scope(bot,o,false)==null) found.add(o);
            }
        }
        return found;
    }

    /**
     * scenarioEnd <id>: destroys every reachable object tagged with the id
     * for this bot (at most SCENARIO_END_MAX), clears the open record when
     * it is this id, and removes the bot's fixture.t.* test objvars. Safe to
     * repeat: a second call reports destroyed=0.
     */
    public String scenarioEnd(String value) throws InterruptedException {
        Object[] q=request(value,"scenarioEnd",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE);
        if(id==null) return invalidArgs("scenario");
        java.util.List<obj_id> found=reachableTagged(bot,id);
        int destroyed=0,failed=0,gone=0;
        boolean truncated=false;
        for(obj_id o:found) {
            if(destroyed+failed>=SCENARIO_END_MAX) {truncated=true;break;}
            if(!exists(o)) {gone++;continue;}  // went with a destroyed container
            if(destroyObject(o)) destroyed++;
            else failed++;
        }
        String open=openScenario(bot);
        boolean wasOpen=id.equals(open);
        if(wasOpen && !truncated) {removeObjVar(bot,OPEN_VAR);removeObjVar(bot,CREATED_VAR);}
        boolean vars=hasObjVar(bot,TEST_VAR_ROOT);
        if(vars) removeObjVar(bot,TEST_VAR_ROOT);
        StringBuilder sb=start(failed==0 && !truncated?"ok":"refused");
        kv(sb,"scenario",id);kv(sb,"destroyed",destroyed);kv(sb,"with_container",gone);kv(sb,"failed",failed);
        kv(sb,"truncated",truncated);kv(sb,"was_open",wasOpen);kv(sb,"open",wasOpen && !truncated?"none":(open==null?"none":open));
        kv(sb,"test_vars_cleared",vars);kv(sb,"scene",getCurrentSceneName());
        return sb.toString();
    }

    /** scenarioList <id>: rows oid, template, where (carried|building|world), distance for each reachable tagged object. */
    public String scenarioList(String value) throws InterruptedException {
        Object[] q=request(value,"scenarioList",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE);
        if(id==null) return invalidArgs("scenario");
        java.util.List<obj_id> found=reachableTagged(bot,id);
        obj_id building=botBuilding(bot);
        String open=openScenario(bot);
        StringBuilder sb=start("ok");
        kv(sb,"scenario",id);kv(sb,"open",open==null?"none":open);kv(sb,"count",found.size());
        kv(sb,"created",hasObjVar(bot,CREATED_VAR)?getIntObjVar(bot,CREATED_VAR):0);kv(sb,"scene",getCurrentSceneName());
        int[] rc=new int[2];
        for(obj_id o:found) {
            obj_id top=getTopMostContainer(o);
            String where=bot.equals(top)?"carried":(building!=null && building.equals(top)?"building":"world");
            row(sb,rc,o,getTemplateName(o),where,String.format("%.1f",getDistance(bot,o)));
        }
        return end(sb,rc);
    }

    // ------------------------------------------------------------------
    // Objects
    // ------------------------------------------------------------------

    /** createAt <scenario> <template> <x> <z> <yaw>: an object on the terrain at a world point within reach, in the bot's scene. */
    public String createAt(String value) throws InterruptedException {
        Object[] q=request(value,"createAt",5,5);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE),t=template(args[1]);
        Float x=num(args[2],-WORLD_XZ_MAX,WORLD_XZ_MAX),z=num(args[3],-WORLD_XZ_MAX,WORLD_XZ_MAX),yaw=num(args[4],-YAW_MAX,YAW_MAX);
        if(id==null || t==null || x==null || z==null || yaw==null) return invalidArgs("createAt");
        String s=mayCreate(bot,id,1);
        if(s!=null) return fail(s);
        String scene=getCurrentSceneName();
        location b=getWorldLocation(bot);
        location target=new location(x,getHeightAtLocation(x,z),z,scene);
        if(b==null || getDistance(target,b)>SCOPE_RANGE) return fail("out-of-scope reason=destination-distance");
        obj_id o=createObject(t,target);
        if(!tag(bot,o,id)) return fail("refused reason=create-failed template="+enc(t));
        setYaw(o,yaw);
        StringBuilder sb=start("ok");
        kv(sb,"object",o);kv(sb,"template",t);kv(sb,"scenario",id);kv(sb,"scene",scene);
        kv(sb,"x",target.x);kv(sb,"y",target.y);kv(sb,"z",target.z);kv(sb,"yaw",getYaw(o));
        return sb.toString();
    }

    /** createInCell <scenario> <template> <buildingOid> <cell> <x> <y> <z> <yaw>: an object at a cell-local spot of an in-scope building. */
    public String createInCell(String value) throws InterruptedException {
        Object[] q=request(value,"createInCell",8,8);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE),t=template(args[1]),cell=match(args[3],CELL_RE);
        obj_id building=oid(args[2]);
        Float x=num(args[4],-CELL_LOCAL_MAX,CELL_LOCAL_MAX),y=num(args[5],-CELL_LOCAL_MAX,CELL_LOCAL_MAX);
        Float z=num(args[6],-CELL_LOCAL_MAX,CELL_LOCAL_MAX),yaw=num(args[7],-YAW_MAX,YAW_MAX);
        if(id==null || t==null || building==null || cell==null || x==null || y==null || z==null || yaw==null) return invalidArgs("createInCell");
        String s=scope(bot,building,false);
        if(s==null) s=mayCreate(bot,id,1);
        if(s!=null) return fail(s);
        obj_id c=getCellId(building,cell);
        location b=getLocation(building);
        if(!isIdValid(c) || b==null) return fail("refused reason=no-such-cell");
        obj_id o=createObject(t,new location(x,y,z,b.area,c));
        if(!tag(bot,o,id)) return fail("refused reason=create-failed template="+enc(t));
        setYaw(o,yaw);
        StringBuilder sb=start("ok");
        kv(sb,"object",o);kv(sb,"template",t);kv(sb,"scenario",id);kv(sb,"building",building);kv(sb,"cell",cell);
        return sb.toString();
    }

    /** createInInventory <scenario> <template> [count 1..10]: objects in the bot's inventory. */
    public String createInInventory(String value) throws InterruptedException {
        Object[] q=request(value,"createInInventory",2,3);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE),t=template(args[1]);
        Integer count=args.length==3?integer(args[2],1,INVENTORY_COUNT_MAX):Integer.valueOf(1);
        if(id==null || t==null || count==null) return invalidArgs("createInInventory");
        String s=mayCreate(bot,id,count);
        if(s!=null) return fail(s);
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        int made=0,failed=0;
        StringBuilder sb=start("ok");
        kv(sb,"template",t);kv(sb,"scenario",id);
        int[] rc=new int[2];
        for(int i=0;i<count;i++) {
            obj_id o=createObject(t,inventory,"");
            if(tag(bot,o,id)) {made++;row(sb,rc,o);}
            else failed++;
        }
        kv(sb,"created",made);kv(sb,"failed",failed);
        return end(sb,rc);
    }

    /** destroyCreated <oid>: destroys one object or creature the fixture created for this bot. */
    public String destroyCreated(String value) throws InterruptedException {
        Object[] q=request(value,"destroyCreated",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id o=oid(args[0]);
        if(o==null) return invalidArgs("objectOid");
        String s=created(bot,o,false);
        if(s!=null) return fail(s);
        String id=taggedFor(bot,o);
        boolean ok=destroyObject(o);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"object",o);kv(sb,"scenario",id);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Creatures
    // ------------------------------------------------------------------

    /** spawnCreature <scenario> <creatureName> <dx> <dz> [level 1..90]: a creatures.tab creature near the bot. */
    public String spawnCreature(String value) throws InterruptedException {
        Object[] q=request(value,"spawnCreature",4,5);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String id=match(args[0],SCENARIO_RE),name=match(args[1],CREATURE_RE);
        Float dx=num(args[2],-SPAWN_OFFSET_MAX,SPAWN_OFFSET_MAX),dz=num(args[3],-SPAWN_OFFSET_MAX,SPAWN_OFFSET_MAX);
        Integer level=args.length==5?integer(args[4],SPAWN_LEVEL_MIN,SPAWN_LEVEL_MAX):Integer.valueOf(-1);
        if(id==null || name==null || dx==null || dz==null || level==null) return invalidArgs("spawnCreature");
        String s=mayCreate(bot,id,1);
        if(s!=null) return fail(s);
        if(dataTableSearchColumnForString(name,"creatureName",create.CREATURE_TABLE)<0) return fail("refused reason=unknown-creature name="+enc(name));
        location target=near(bot,dx,dz);
        if(target==null) return fail("refused reason=no-location");
        obj_id c=create.createCreature(name,target,level,true,false);
        if(isIdValid(c) && isPlayer(c)) {destroyObject(c);return fail("refused reason=player-template");}
        if(!tag(bot,c,id)) return fail("refused reason=spawn-failed name="+enc(name));
        StringBuilder sb=start("ok");
        kv(sb,"creature",c);kv(sb,"name",name);kv(sb,"scenario",id);kv(sb,"template",getTemplateName(c));
        kv(sb,"level",getLevel(c));kv(sb,"distance",String.format("%.1f",getDistance(bot,c)));
        return sb.toString();
    }

    /** creatureAttack <creatureOid>: the fixture-spawned creature starts combat with the bot. */
    public String creatureAttack(String value) throws InterruptedException {
        Object[] q=request(value,"creatureAttack",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        if(c==null) return invalidArgs("creatureOid");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        if(isDead(c)) return fail("refused reason=dead creature="+c);
        setWantSawAttackTriggers(c,true);
        startCombat(c,bot);
        return P+"ok creature="+c+" target="+bot;
    }

    /** creaturePassive <creatureOid>: stops its combat, ignores attack triggers, stands still (sentinel). */
    public String creaturePassive(String value) throws InterruptedException {
        Object[] q=request(value,"creaturePassive",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        if(c==null) return invalidArgs("creatureOid");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        stopCombat(c);
        setWantSawAttackTriggers(c,false);
        ai_lib.setDefaultCalmBehavior(c,ai_lib.BEHAVIOR_SENTINEL);
        stop(c);
        return P+"ok creature="+c+" passive=true";
    }

    /** creatureInvulnerable <creatureOid> <on|off>. */
    public String creatureInvulnerable(String value) throws InterruptedException {
        Object[] q=request(value,"creatureInvulnerable",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        String flag=match(args[1],ONOFF_RE);
        if(c==null || flag==null) return invalidArgs("creatureInvulnerable");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        boolean ok=setInvulnerable(c,"on".equals(flag));
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"creature",c);kv(sb,"invulnerable",isInvulnerable(c));
        return sb.toString();
    }

    /** creatureMove <creatureOid> <dx> <dz>: the creature paths to a point near the bot (AI movement). */
    public String creatureMove(String value) throws InterruptedException {
        Object[] q=request(value,"creatureMove",3,3);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        Float dx=num(args[1],-SPAWN_OFFSET_MAX,SPAWN_OFFSET_MAX),dz=num(args[2],-SPAWN_OFFSET_MAX,SPAWN_OFFSET_MAX);
        if(c==null || dx==null || dz==null) return invalidArgs("creatureMove");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        location target=near(bot,dx,dz);
        if(target==null) return fail("refused reason=no-location");
        pathTo(c,target);
        StringBuilder sb=start("ok");
        kv(sb,"creature",c);kv(sb,"x",target.x);kv(sb,"y",target.y);kv(sb,"z",target.z);kv(sb,"cell",isIdValid(target.cell)?target.cell:"none");
        return sb.toString();
    }

    /** creatureKill <creatureOid>. */
    public String creatureKill(String value) throws InterruptedException {
        Object[] q=request(value,"creatureKill",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        if(c==null) return invalidArgs("creatureOid");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        boolean ok=kill(c);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"creature",c);kv(sb,"dead",isDead(c));
        return sb.toString();
    }

    /** creatureDespawn <creatureOid>: destroys a fixture-spawned creature. */
    public String creatureDespawn(String value) throws InterruptedException {
        Object[] q=request(value,"creatureDespawn",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id c=oid(args[0]);
        if(c==null) return invalidArgs("creatureOid");
        String s=created(bot,c,true);
        if(s!=null) return fail(s);
        boolean ok=destroyObject(c);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"creature",c);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Quests
    // ------------------------------------------------------------------

    /** Quest crc for a valid quest name, else null. */
    private static Integer questId(String name) throws InterruptedException {
        if(match(name,QUEST_RE)==null || !groundquests.isValidQuestName(name)) return null;
        return groundquests.getQuestIdFromString(name);
    }

    /** questGrant <questName>: activates a ground quest on the bot without the acceptance window. */
    public String questGrant(String value) throws InterruptedException {
        Object[] q=request(value,"questGrant",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        if(match(args[0],QUEST_RE)==null) return invalidArgs("questName");
        Integer id=questId(args[0]);
        if(id==null) return fail("refused reason=unknown-quest quest="+enc(args[0]));
        if(groundquests.isQuestDisabled(args[0])) return fail("refused reason=disabled-quest quest="+enc(args[0]));
        if(questIsQuestActive(id,bot)) return P+"ok quest="+enc(args[0])+" already=true active=true";
        int result=questActivateQuest(id,bot,bot);
        StringBuilder sb=start("ok");
        kv(sb,"quest",args[0]);kv(sb,"already",false);kv(sb,"result",result);kv(sb,"active",questIsQuestActive(id,bot));
        return sb.toString();
    }

    /** questComplete <questName>: completes an active quest (its rewards are granted by the quest system). */
    public String questComplete(String value) throws InterruptedException {
        Object[] q=request(value,"questComplete",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        if(match(args[0],QUEST_RE)==null) return invalidArgs("questName");
        Integer id=questId(args[0]);
        if(id==null) return fail("refused reason=unknown-quest quest="+enc(args[0]));
        if(!questIsQuestActive(id,bot)) return fail("refused reason=not-active quest="+enc(args[0]));
        int result=questCompleteQuest(id,bot);
        StringBuilder sb=start("ok");
        kv(sb,"quest",args[0]);kv(sb,"result",result);kv(sb,"complete",questIsQuestComplete(id,bot));
        return sb.toString();
    }

    /** questClear <questName>: removes the quest from the bot, active or completed. */
    public String questClear(String value) throws InterruptedException {
        Object[] q=request(value,"questClear",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        if(match(args[0],QUEST_RE)==null) return invalidArgs("questName");
        Integer id=questId(args[0]);
        if(id==null) return fail("refused reason=unknown-quest quest="+enc(args[0]));
        boolean had=questIsQuestActive(id,bot) || questIsQuestComplete(id,bot);
        questClearQuest(id,bot);
        StringBuilder sb=start("ok");
        kv(sb,"quest",args[0]);kv(sb,"had",had);
        kv(sb,"active",questIsQuestActive(id,bot));kv(sb,"complete",questIsQuestComplete(id,bot));
        return sb.toString();
    }

    /** questSignal <signal>: sends a ground quest signal to the bot (delivered by message, after this reply). */
    public String questSignal(String value) throws InterruptedException {
        Object[] q=request(value,"questSignal",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String signal=match(args[0],SIGNAL_RE);
        if(signal==null) return invalidArgs("signal");
        groundquests.sendSignal(bot,signal);
        return P+"ok signal="+signal+" delivery=message";
    }

    /** quests: rows active,<name> and completed,<name> (at most MAX_ROWS together). */
    public String quests(String value) throws InterruptedException {
        Object[] q=request(value,"quests",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        int[] active=questGetAllActiveQuestIds(bot),done=questGetAllCompletedQuestIds(bot);
        StringBuilder sb=start("ok");
        kv(sb,"active",active==null?0:active.length);kv(sb,"completed",done==null?0:done.length);
        int[] rc=new int[2];
        if(active!=null) for(int id:active) row(sb,rc,"active",questGetQuestName(id));
        if(done!=null) for(int id:done) row(sb,rc,"completed",questGetQuestName(id));
        return end(sb,rc);
    }

    // ------------------------------------------------------------------
    // Test objvars (fixture.t.*)
    // ------------------------------------------------------------------

    /** setTestVar <self|oid> <name> <int|float|string> <value>: sets fixture.t.<name> on the bot or a fixture-created object. */
    public String setTestVar(String value) throws InterruptedException {
        Object[] q=request(value,"setTestVar",4,4);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String name=match(args[1],VAR_NAME_RE),type=match(args[2],VAR_TYPE_RE),v=match(args[3],VAR_VALUE_RE);
        if(name==null || type==null || v==null) return invalidArgs("setTestVar");
        Object[] target=varTarget(bot,args[0]);
        if(target[0]!=null) return (String)target[0];
        obj_id o=(obj_id)target[1];
        String var=TEST_VAR_ROOT+"."+name;
        boolean ok;
        if("int".equals(type)) {
            Integer i=integer(v,-VAR_INT_MAX,VAR_INT_MAX);
            if(i==null) return invalidArgs("int-value");
            ok=setObjVar(o,var,i.intValue());
        } else if("float".equals(type)) {
            Float f=num(v,-VAR_FLOAT_MAX,VAR_FLOAT_MAX);
            if(f==null) return invalidArgs("float-value");
            ok=setObjVar(o,var,f.floatValue());
        } else ok=setObjVar(o,var,v);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"object",o);kv(sb,"name",var);kv(sb,"type",type);kv(sb,"value",v);
        return sb.toString();
    }

    /** clearTestVar <self|oid> <name>: removes fixture.t.<name> (and anything under it). */
    public String clearTestVar(String value) throws InterruptedException {
        Object[] q=request(value,"clearTestVar",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String name=match(args[1],VAR_NAME_RE);
        if(name==null) return invalidArgs("name");
        Object[] target=varTarget(bot,args[0]);
        if(target[0]!=null) return (String)target[0];
        obj_id o=(obj_id)target[1];
        String var=TEST_VAR_ROOT+"."+name;
        boolean had=hasObjVar(o,var);
        if(had) removeObjVar(o,var);
        return P+"ok object="+o+" name="+var+" had="+had;
    }

    /** getTestVar <self|oid> [name]: one test objvar's type and value, or rows of all fixture.t.* entries. */
    public String getTestVar(String value) throws InterruptedException {
        Object[] q=request(value,"getTestVar",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String name=args.length==2?match(args[1],VAR_NAME_RE):"";
        if(name==null) return invalidArgs("name");
        Object[] target=varTarget(bot,args[0]);
        if(target[0]!=null) return (String)target[0];
        obj_id o=(obj_id)target[1];
        StringBuilder sb=start("ok");
        kv(sb,"object",o);
        if(name.length()>0) {
            String var=TEST_VAR_ROOT+"."+name;
            kv(sb,"name",var);
            if(!hasObjVar(o,var)) {kv(sb,"present",false);return sb.toString();}
            obj_var_list parent=getObjVarList(o,var.substring(0,var.lastIndexOf('.')));
            obj_var v=parent==null?null:parent.getObjVar(var.substring(var.lastIndexOf('.')+1));
            Object data=v==null?null:v.getData();
            kv(sb,"present",true);kv(sb,"type",typeOf(data));kv(sb,"value",data);
            return sb.toString();
        }
        int[] rc=new int[2];
        obj_var_list all=getObjVarList(o,TEST_VAR_ROOT);
        if(all!=null) for(int i=0;i<all.getNumItems();i++) {
            obj_var v=all.getObjVar(i);
            if(v!=null) row(sb,rc,v.getName(),typeOf(v.getData()),v.getData());
        }
        return end(sb,rc);
    }

    private static String typeOf(Object data) {
        if(data instanceof Integer) return "int";
        if(data instanceof Float) return "float";
        if(data instanceof String) return "string";
        return data==null?"none":"other";
    }

    // ------------------------------------------------------------------
    // Travel and facing
    // ------------------------------------------------------------------

    /**
     * warpScene <scene> <x> <y> <z>: warpPlayer of the bot to a world point
     * of one of the open-world SCENES. The hand-off is asynchronous; the
     * runner waits until the bot query finds the bot in the reply's scene.
     */
    public String warpScene(String value) throws InterruptedException {
        Object[] q=request(value,"warpScene",4,4);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String scene=sceneName(args[0]);
        Float x=num(args[1],-WORLD_XZ_MAX,WORLD_XZ_MAX),y=num(args[2],WORLD_Y_MIN,WORLD_Y_MAX),z=num(args[3],-WORLD_XZ_MAX,WORLD_XZ_MAX);
        if(scene==null || x==null || y==null || z==null) return invalidArgs("warpScene");
        String from=getCurrentSceneName();
        String open=openScenario(bot);
        warpPlayer(bot,scene,x,y,z,(obj_id)null,0.0f,0.0f,0.0f);
        StringBuilder sb=start("ok");
        kv(sb,"scene",scene);kv(sb,"from",from);kv(sb,"x",x);kv(sb,"y",y);kv(sb,"z",z);
        kv(sb,"requested",true);kv(sb,"open_scenario",open==null?"none":open);
        return sb.toString();
    }

    /** face <yawDeg>: sets the bot's heading. */
    public String face(String value) throws InterruptedException {
        Object[] q=request(value,"face",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Float yaw=num(args[0],-YAW_MAX,YAW_MAX);
        if(yaw==null) return invalidArgs("yaw");
        boolean ok=setYaw(bot,yaw);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"yaw",getYaw(bot));
        return sb.toString();
    }
}
