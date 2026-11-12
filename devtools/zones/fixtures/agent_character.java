package script.fixture;
import script.*;
import script.library.*;

/**
 * Op family "character": arrange and assert the test character itself.
 *
 * Invoked through the CentralServer console:
 *   game <serverId> runScript fixture.agent_character <method> <oid>:<stationId>:<characterName> [typed args...]
 *
 * The isolation and identity guard and its helpers are copied verbatim from
 * agent_fixture.java. Every public method answers one line
 * "agent_character=<status> key=value ..." and acts only on the one exact
 * registered non-god bot. Nothing here grants god mode or an admin level,
 * attaches a script or runs a free-form command. Level and profession use
 * the respec library the server uses for its own respec (its no-items
 * variant: nothing is placed in the inventory); credits use the money
 * library; standing uses the factions library; buffs the buff library.
 * Every numeric argument has a named cap below. giveStaticCount tags and
 * counts what it creates exactly as the scenario family does (the scenario
 * helpers below are copied verbatim from agent_scenario.java). One
 * top-level type only, so it deploys as a single compiled file.
 */
public class agent_character extends base_script {
    private static final String P="agent_character=";
    private static final int MAX_ROWS=200;
    private static final float SCOPE_RANGE=256.0f;
    private static final int CHAIN_MAX=64;
    private static final String OID_RE="[1-9][0-9]{0,18}";
    private static final String NUM_RE="-?[0-9]{1,5}(\\.[0-9]{1,6})?";
    private static final String INT_RE="-?[0-9]{1,9}";
    private static final String NAME_RE="[a-z0-9_]{1,64}";
    private static final String CELL_RE="[A-Za-z0-9_]{1,64}";

    // Scenario tagging (sources/interface.md): the same objvars and cap as agent_scenario.java.
    private static final String SCENARIO_RE="[a-z][a-z0-9_]{0,31}";
    private static final String TAG_SCENARIO="fixture.scenario";
    private static final String TAG_OWNER="fixture.owner";
    private static final String OPEN_VAR="fixture.scenario_open";
    private static final String CREATED_VAR="fixture.scenario_created";
    private static final String IDS_VAR="fixture.scenario_ids";
    private static final int SCENARIO_CREATE_MAX=100;
    // Objvar roots resetCharacter clears: test objvars, snapshots, and this family's own record
    // of what it changed (applied buffs, original faction, pvp type and standings).
    private static final String TEST_VAR_ROOT="fixture.t";
    private static final String SNAPSHOT_ROOT="fixture.snapshot";
    private static final String RESET_ROOT="fixture.r";

    // Named caps; the Python module swg_test_studio/fixture_ops/character.py uses the same values.
    private static final int POOL_MAX=500000;
    private static final int LEVEL_MAX=90;
    private static final int CREDITS_MAX=10000000;
    private static final float STANDING_MIN=-5000.0f;
    private static final float STANDING_MAX=50000.0f;
    private static final int BUFF_SECONDS_MAX=3600;
    // applyBuff accepts only these buff-table families: medic stat buffs and food, drink and
    // foraged consumables (attribute and skill-mod effects, no state, callback or immunity);
    // a name containing any BUFF_DENY part is refused even then.
    private static final String[] BUFF_PREFIXES={"me_buff_","drink_","dish_","dessert_","foraged_"};
    private static final String[] BUFF_DENY={"immun","invuln","stasis","god","gm_","admin"};
    // The NPC respec raises a level below this to it; setProfession does the same.
    private static final int RESPEC_LEVEL_MIN=5;
    private static final int GIVE_COUNT_MAX=25;
    private static final int REVOKE_MAX=500;

    // Argument regexes, identical to the Python TYPES of the family.
    private static final String POOL_RE="[0-9]{1,6}";
    private static final String LEVEL_RE="[0-9]{1,2}";
    private static final String CREDITS_RE="[0-9]{1,8}";
    private static final String FACTION_RE="[A-Za-z][A-Za-z0-9_]{0,47}";
    private static final String STANDING_RE="-?[0-9]{1,5}(\\.[0-9]{1,2})?";
    private static final String SECONDS_RE="[0-9]{1,5}";
    private static final String COUNT_RE="[0-9]{1,2}";
    private static final String SKILL_PATTERN_RE="[A-Za-z0-9_.*^$|()\\[\\]+?-]{1,64}";
    // gm.getRoadmapList() of a Dec 2011 script tree; re-checked against it at run time.
    private static final String[] PROFESSIONS={
        "smuggler_1a","bounty_hunter_1a","officer_1a","commando_1a","force_sensitive_1a",
        "medic_1a","spy_1a","entertainer_1a","trader_0a","trader_0b","trader_0c","trader_0d"
    };
    private static final String[] ALIGNED={"Imperial","Rebel","Neutral"};
    private static final String[] PVP_TYPES={"neutral","covert","declared","onleave"};
    private static final String[] POSTURE_NAMES={"upright","crouched","prone","sitting","knocked_down"};
    private static final int[] POSTURE_VALUES={POSTURE_UPRIGHT,POSTURE_CROUCHED,POSTURE_PRONE,POSTURE_SITTING,POSTURE_KNOCKED_DOWN};

    // ------------------------------------------------------------------
    // Guard: environment, identity, arguments
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
    private static String name(String s) {return s!=null && s.matches(NAME_RE)?s:null;}
    private static String cellName(String s) {return s!=null && s.matches(CELL_RE)?s:null;}
    /** Comma list of 1..max entries, each matching re; null on any violation. */
    private static String[] list(String s,String re,int max) {
        if(s==null || s.length()==0 || s.length()>2048) return null;
        String[] parts=s.split(",",-1);
        if(parts.length<1 || parts.length>max) return null;
        for(String part:parts) if(!part.matches(re)) return null;
        return parts;
    }

    // ------------------------------------------------------------------
    // Scope: what the bot may touch
    // ------------------------------------------------------------------

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

    // ------------------------------------------------------------------
    // Output: "agent_fixture=<status> key=value ... [row=a,b,c ...] [rows=N truncated=B]"
    // ------------------------------------------------------------------

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
    // Family helpers
    // ------------------------------------------------------------------

    /** Index of s in allowed, or -1. */
    private static int pick(String s,String[] allowed) {
        if(s==null) return -1;
        for(int i=0;i<allowed.length;i++) if(allowed[i].equals(s)) return i;
        return -1;
    }
    /** An integer that matches re and lies in lo..hi, else null. */
    private static Integer bounded(String s,String re,int lo,int hi) {
        if(s==null || !s.matches(re)) return null;
        return integer(s,lo,hi);
    }
    /** A faction of the faction table that players may hold standing in. */
    private static boolean playerFaction(String f) throws InterruptedException {
        if(f==null || !f.matches(FACTION_RE)) return false;
        int row=factions.getFactionNumber(f);
        return row>=0 && dataTableGetInt(factions.FACTION_TABLE,row,"playerAllowed")==1;
    }
    private static String postureName(int p) {
        for(int i=0;i<POSTURE_VALUES.length;i++) if(POSTURE_VALUES[i]==p) return POSTURE_NAMES[i];
        if(p==POSTURE_INCAPACITATED) return "incapacitated";
        if(p==POSTURE_DEAD) return "dead";
        return String.valueOf(p);
    }
    private static String pvpName(int t) {
        if(t==PVPTYPE_NEUTRAL) return "neutral";
        if(t==PVPTYPE_COVERT) return "covert";
        if(t==PVPTYPE_DECLARED) return "declared";
        return String.valueOf(t);
    }
    private static String factionName(obj_id bot) throws InterruptedException {
        int f=pvpGetAlignedFaction(bot);
        if(f==0) return "none";
        String n=factions.getFactionNameByHashCode(f);
        return n==null?"unknown":n;
    }
    private static boolean roadmap(String template) throws InterruptedException {
        String[] list=gm.getRoadmapList();
        if(list!=null) for(String r:list) if(r.equals(template)) return true;
        return false;
    }
    /** A buff applyBuff may apply: one of BUFF_PREFIXES and none of BUFF_DENY. */
    private static boolean allowedBuff(String n) {
        if(n==null) return false;
        for(String deny:BUFF_DENY) if(n.contains(deny)) return false;
        for(String prefix:BUFF_PREFIXES) if(n.startsWith(prefix)) return true;
        return false;
    }
    /** Null when a cash plus bank total stays within CREDITS_MAX, else a refusal. */
    private static String creditCap(long total) {
        return total>CREDITS_MAX?"refused reason=credits-cap total="+total+" cap="+CREDITS_MAX:null;
    }
    /** Records the bot's aligned faction and pvp type once, before the first change (resetCharacter restores them). */
    private static void rememberFaction(obj_id bot) throws InterruptedException {
        if(hasObjVar(bot,RESET_ROOT+".faction")) return;
        setObjVar(bot,RESET_ROOT+".faction",pvpGetAlignedFaction(bot));
        setObjVar(bot,RESET_ROOT+".pvp",pvpGetType(bot));
    }
    /** The skill-pattern limits of the core grantSkills: null when the pattern is refused. */
    private static java.util.regex.Pattern skillPattern(String re) {
        if(re==null || !re.matches(SKILL_PATTERN_RE) || re.matches(".*\\)[*+?].*")) return null;
        int unbounded=0,quantifiers=0;
        for(int i=0;i<re.length();i++) {
            char ch=re.charAt(i);
            if(ch=='*' || ch=='+') unbounded++;
            if(ch=='*' || ch=='+' || ch=='?') quantifiers++;
        }
        if(unbounded>2 || quantifiers>3) return null;
        try {return java.util.regex.Pattern.compile(re);}
        catch(RuntimeException e) {return null;}
    }
    /** Pools, level, credits, faction, posture and profession of the bot. */
    private static StringBuilder sheet(StringBuilder sb,obj_id bot) throws InterruptedException {
        kv(sb,"health",getAttrib(bot,HEALTH));kv(sb,"health_max",getMaxAttrib(bot,HEALTH));
        kv(sb,"action",getAttrib(bot,ACTION));kv(sb,"action_max",getMaxAttrib(bot,ACTION));
        kv(sb,"level",getLevel(bot));kv(sb,"combat_level",respec.getCombatLevel(bot));
        kv(sb,"cash",getCashBalance(bot));kv(sb,"bank",getBankBalance(bot));kv(sb,"total_credits",getTotalMoney(bot));
        kv(sb,"faction",factionName(bot));kv(sb,"faction_id",pvpGetAlignedFaction(bot));kv(sb,"pvp_type",pvpName(pvpGetType(bot)));
        kv(sb,"standing_imperial",factions.getFactionStanding(bot,"Imperial"));
        kv(sb,"standing_rebel",factions.getFactionStanding(bot,"Rebel"));
        kv(sb,"posture",postureName(getPosture(bot)));
        kv(sb,"incapacitated",isIncapacitated(bot));kv(sb,"dead",isDead(bot));
        kv(sb,"profession_id",utils.getPlayerProfession(bot));kv(sb,"template",getSkillTemplate(bot));
        String[] skills=getSkillListingForPlayer(bot);
        kv(sb,"skills",skills==null?0:skills.length);
        return sb;
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

    /** The ids the open scenario created and has not destroyed (fixture.scenario_ids). */
    private static java.util.List<obj_id> liveIds(obj_id bot) throws InterruptedException {
        java.util.List<obj_id> ids=new java.util.ArrayList<obj_id>();
        obj_id[] stored=hasObjVar(bot,IDS_VAR)?getObjIdArrayObjVar(bot,IDS_VAR):null;
        if(stored!=null) for(obj_id x:stored) if(isIdValid(x) && !ids.contains(x)) ids.add(x);
        return ids;
    }

    /** Replaces the record of live created ids; an empty list removes it. */
    private static boolean storeIds(obj_id bot,java.util.List<obj_id> ids) throws InterruptedException {
        if(ids.isEmpty()) {removeObjVar(bot,IDS_VAR);return true;}
        return setObjVar(bot,IDS_VAR,ids.toArray(new obj_id[0]));
    }

    /** Tags a freshly created object, records its id and counts it against the cap; destroys it when any of that fails. */
    private static boolean tag(obj_id bot,obj_id o,String id) throws InterruptedException {
        if(!isIdValid(o)) return false;
        if(!setObjVar(o,TAG_SCENARIO,id) || !setObjVar(o,TAG_OWNER,bot)) {destroyObject(o);return false;}
        java.util.List<obj_id> ids=liveIds(bot);
        ids.add(o);
        if(!storeIds(bot,ids)) {destroyObject(o);return false;}
        int created=hasObjVar(bot,CREATED_VAR)?getIntObjVar(bot,CREATED_VAR):0;
        setObjVar(bot,CREATED_VAR,created+1);
        return true;
    }

    /** Drops a destroyed object from the record of live created ids. */
    private static void forget(obj_id bot,obj_id o) throws InterruptedException {
        java.util.List<obj_id> ids=liveIds(bot);
        if(ids.remove(o)) storeIds(bot,ids);
    }

    private static StringBuilder wallet(StringBuilder sb,obj_id bot) throws InterruptedException {
        kv(sb,"cash",getCashBalance(bot));kv(sb,"bank",getBankBalance(bot));
        return sb;
    }

    // ------------------------------------------------------------------
    // Read-backs
    // ------------------------------------------------------------------

    /** stats: pools, level, combat level, credits, faction, standing, posture, profession, skill count. */
    public String stats(String value) throws InterruptedException {
        Object[] q=request(value,"stats",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        return sheet(kv(start("ok"),"player",bot),bot).toString();
    }

    /** buffs [name]: rows of buff name and seconds left; with a name also has=true|false. */
    public String buffs(String value) throws InterruptedException {
        Object[] q=request(value,"buffs",0,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String only=null;
        if(args.length==1) {
            only=name(args[0]);
            if(only==null) return invalidArgs("buffName");
        }
        int[] crcs=buff.getAllBuffs(bot);
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        int count=0;
        if(crcs!=null) for(int crc:crcs) {
            String n=buff.getBuffNameFromCrc(crc);
            count++;
            row(sb,rc,n==null?String.valueOf(crc):n,String.format(java.util.Locale.ROOT,"%.1f",buff.getBuffTimeRemaining(bot,crc)));
        }
        kv(sb,"count",count);
        if(only!=null) {kv(sb,"buff",only);kv(sb,"has",buff.hasBuff(bot,only));}
        return end(sb,rc);
    }

    /** standing <faction>: the bot's standing and its cap in one faction of the faction table. */
    public String standing(String value) throws InterruptedException {
        Object[] q=request(value,"standing",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String f=args[0];
        if(f==null || !f.matches(FACTION_RE)) return invalidArgs("faction");
        if(factions.getFactionNumber(f)<0) return fail("refused reason=unknown-faction faction="+enc(f));
        StringBuilder sb=start("ok");
        kv(sb,"faction",f);kv(sb,"standing",factions.getFactionStanding(bot,f));kv(sb,"max",factions.getFactionMax(bot,f));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Pools and condition
    // ------------------------------------------------------------------

    /** Shared body of the four pool setters; q is the request(...) result. */
    private String pool(Object[] q,int attrib,boolean max) throws InterruptedException {
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer v=bounded(args[0],POOL_RE,1,POOL_MAX);
        if(v==null) return invalidArgs("pool");
        if(isDead(bot) || isIncapacitated(bot)) return fail("refused reason=incapacitated use=revive");
        boolean ok;
        if(max) ok=setMaxAttrib(bot,attrib,v);
        else {
            int cap=getMaxAttrib(bot,attrib);
            if(v>cap) return fail("refused reason=above-max max="+cap);
            ok=setAttrib(bot,attrib,v);
        }
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"pool",attrib==HEALTH?"health":"action");
        kv(sb,"current",getAttrib(bot,attrib));kv(sb,"max",getMaxAttrib(bot,attrib));
        return sb.toString();
    }

    /** setHealth <1..POOL_MAX>: current health (setAttrib), at most the current maximum. */
    public String setHealth(String value) throws InterruptedException {
        Object[] q=request(value,"setHealth",1,1);
        return pool(q,HEALTH,false);
    }

    /** setAction <1..POOL_MAX>: current action (setAttrib), at most the current maximum. */
    public String setAction(String value) throws InterruptedException {
        Object[] q=request(value,"setAction",1,1);
        return pool(q,ACTION,false);
    }

    /** setMaxHealth <1..POOL_MAX>: maximum health (setMaxAttrib). */
    public String setMaxHealth(String value) throws InterruptedException {
        Object[] q=request(value,"setMaxHealth",1,1);
        return pool(q,HEALTH,true);
    }

    /** setMaxAction <1..POOL_MAX>: maximum action (setMaxAttrib). */
    public String setMaxAction(String value) throws InterruptedException {
        Object[] q=request(value,"setMaxAction",1,1);
        return pool(q,ACTION,true);
    }

    /** healFull: healing.fullHeal, then health and action to their maximum. */
    public String healFull(String value) throws InterruptedException {
        Object[] q=request(value,"healFull",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        if(isDead(bot) || isIncapacitated(bot)) return fail("refused reason=incapacitated use=revive");
        boolean ok=healing.fullHeal(bot);
        setAttrib(bot,HEALTH,getMaxAttrib(bot,HEALTH));
        setAttrib(bot,ACTION,getMaxAttrib(bot,ACTION));
        return sheet(start(ok?"ok":"refused"),bot).toString();
    }

    /** incapacitate: sets the incapacitated posture (as pclib.clearEffectsForDeath does). */
    public String incapacitate(String value) throws InterruptedException {
        Object[] q=request(value,"incapacitate",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        if(isDead(bot)) return fail("refused reason=dead");
        boolean ok=setPosture(bot,POSTURE_INCAPACITATED);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"posture",postureName(getPosture(bot)));kv(sb,"incapacitated",isIncapacitated(bot));
        return sb.toString();
    }

    /** revive: pclib.resurrectPlayer (clears death effects, full heal); stands an incapacitated bot up. */
    public String revive(String value) throws InterruptedException {
        Object[] q=request(value,"revive",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        boolean was=isDead(bot) || isIncapacitated(bot);
        boolean ok=pclib.resurrectPlayer(bot);
        if(isIncapacitated(bot)) setPostureClientImmediate(bot,POSTURE_UPRIGHT);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"was_down",was);
        return sheet(sb,bot).toString();
    }

    /** setPosture <upright|crouched|prone|sitting|knocked_down>: setPostureClientImmediate. */
    public String setPosture(String value) throws InterruptedException {
        Object[] q=request(value,"setPosture",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        int i=pick(args[0],POSTURE_NAMES);
        if(i<0) return invalidArgs("posture");
        if(isDead(bot) || isIncapacitated(bot)) return fail("refused reason=incapacitated use=revive");
        boolean ok=setPostureClientImmediate(bot,POSTURE_VALUES[i]);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"posture",postureName(getPosture(bot)));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Level, profession, skills
    // ------------------------------------------------------------------

    /** setLevel <1..90>: respec.autoLevelPlayer (raises or lowers), then the respec pool recalculation. */
    public String setLevel(String value) throws InterruptedException {
        Object[] q=request(value,"setLevel",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer level=bounded(args[0],LEVEL_RE,1,LEVEL_MAX);
        if(level==null) return invalidArgs("level");
        String template=getSkillTemplate(bot);
        if(template==null || template.length()==0) return fail("refused reason=no-profession use=setProfession");
        int before=getLevel(bot);
        boolean ok=respec.autoLevelPlayer(bot,level,false);
        if(ok) {
            skill.recalcPlayerPools(bot,true);
            skill.setPlayerStatsForLevel(bot,getLevel(bot));
        }
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"requested",level);kv(sb,"before",before);kv(sb,"level",getLevel(bot));kv(sb,"template",template);
        return sb.toString();
    }

    /**
     * setProfession <roadmap> [level]: the skill part of the NPC respec
     * without its roadmap items: setSkillTemplate,
     * respec.revokeAllSkillsAndExperience, then respec.autoLevelPlayer with
     * withItems=false and the respec pool recalculation. Unlike
     * respec.earnProfessionSkillsViaNpc (whose autoLevelPlayer always grants
     * the untagged roadmap items) it neither removes buffs nor stores called
     * pets and vehicles, and it does not add the class_trader or expertise
     * skill the NPC path adds. Level defaults to the current level; below
     * RESPEC_LEVEL_MIN it is raised to it, as the NPC path does. Only
     * gm.getRoadmapList() names are accepted.
     */
    public String setProfession(String value) throws InterruptedException {
        Object[] q=request(value,"setProfession",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        if(pick(args[0],PROFESSIONS)<0) return invalidArgs("profession");
        Integer level=args.length==2?bounded(args[1],LEVEL_RE,1,LEVEL_MAX):Integer.valueOf(Math.max(1,Math.min(LEVEL_MAX,getLevel(bot))));
        if(level==null) return invalidArgs("level");
        if(!roadmap(args[0])) return fail("refused reason=not-a-roadmap profession="+enc(args[0]));
        String before=getSkillTemplate(bot);
        setSkillTemplate(bot,args[0]);
        respec.revokeAllSkillsAndExperience(bot);
        boolean ok=respec.autoLevelPlayer(bot,Math.max(RESPEC_LEVEL_MIN,level),false);
        if(ok) {
            skill.recalcPlayerPools(bot,true);
            skill.setPlayerStatsForLevel(bot,getLevel(bot));
        }
        StringBuilder sb=start(ok && args[0].equals(getSkillTemplate(bot))?"ok":"refused");
        kv(sb,"before",before);kv(sb,"requested_level",level);kv(sb,"items_granted",false);
        return sheet(sb,bot).toString();
    }

    /** revokeSkills <pattern>: revokes every held skill whose name fully matches (core grantSkills limits). */
    public String revokeSkills(String value) throws InterruptedException {
        Object[] q=request(value,"revokeSkills",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        java.util.regex.Pattern pattern=skillPattern(args[0]);
        if(pattern==null) return invalidArgs("regex");
        String[] held=getSkillListingForPlayer(bot);
        int revoked=0,failed=0;
        boolean capped=false;
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        for(String s:held==null?new String[0]:held) {
            if(s==null || s.length()>128 || !pattern.matcher(s).matches()) continue;
            if(revoked+failed>=REVOKE_MAX) {capped=true;break;}
            revokeSkill(bot,s);
            if(hasSkill(bot,s)) {failed++;row(sb,rc,"failed",s);}
            else {revoked++;row(sb,rc,"revoked",s);}
        }
        kv(sb,"revoked",revoked);kv(sb,"failed",failed);kv(sb,"capped",capped);
        return end(sb,rc);
    }

    /** resetExpertise: utils.fullExpertiseReset (the NPC reallocation path), keeping the expertise skill. */
    public String resetExpertise(String value) throws InterruptedException {
        Object[] q=request(value,"resetExpertise",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        utils.fullExpertiseReset(bot,true);
        if(!hasSkill(bot,"expertise")) grantSkill(bot,"expertise");
        int left=0;
        String[] held=getSkillListingForPlayer(bot);
        for(String s:held==null?new String[0]:held) if(s!=null && s.startsWith("expertise_")) left++;
        StringBuilder sb=start("ok");
        kv(sb,"expertise_skills",left);kv(sb,"has_expertise",hasSkill(bot,"expertise"));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Credits (money library; transfers complete asynchronously)
    // ------------------------------------------------------------------

    /** setBank <0..CREDITS_MAX>: moves the difference from or to the money.ACCT_TEST named account; cash plus bank stays within CREDITS_MAX. */
    public String setBank(String value) throws InterruptedException {
        Object[] q=request(value,"setBank",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer target=bounded(args[0],CREDITS_RE,0,CREDITS_MAX);
        if(target==null) return invalidArgs("credits");
        int bank=getBankBalance(bot),diff=target-bank;
        String cap=creditCap((long)getCashBalance(bot)+target);
        if(cap!=null) return fail(cap);
        boolean ok=diff==0 || (diff>0?money.bankTo(money.ACCT_TEST,bot,diff):money.bankTo(bot,money.ACCT_TEST,-diff));
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"target",target);kv(sb,"bank_before",bank);kv(sb,"pending",diff!=0);
        return wallet(sb,bot).toString();
    }

    /** setCash <0..CREDITS_MAX>: deposits the surplus or withdraws the shortfall from the bank; refused when cash plus bank exceeds CREDITS_MAX. */
    public String setCash(String value) throws InterruptedException {
        Object[] q=request(value,"setCash",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer target=bounded(args[0],CREDITS_RE,0,CREDITS_MAX);
        if(target==null) return invalidArgs("credits");
        int cash=getCashBalance(bot),bank=getBankBalance(bot),diff=target-cash;
        if(diff>bank) return fail("refused reason=bank-too-low bank="+bank+" needed="+diff);
        String cap=creditCap((long)cash+bank);
        if(cap!=null) return fail(cap);
        boolean ok=diff==0 || (diff>0?money.withdraw(bot,diff):money.deposit(bot,-diff));
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"target",target);kv(sb,"cash_before",cash);kv(sb,"pending",diff!=0);
        return wallet(sb,bot).toString();
    }

    /** depositCash <0..CREDITS_MAX>: money.deposit, at most the cash the bot holds. */
    public String depositCash(String value) throws InterruptedException {
        Object[] q=request(value,"depositCash",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer amount=bounded(args[0],CREDITS_RE,0,CREDITS_MAX);
        if(amount==null) return invalidArgs("credits");
        if(amount>getCashBalance(bot)) return fail("refused reason=not-enough-cash cash="+getCashBalance(bot));
        String cap=creditCap((long)getCashBalance(bot)+getBankBalance(bot));
        if(cap!=null) return fail(cap);
        boolean ok=money.deposit(bot,amount);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"amount",amount);kv(sb,"pending",amount!=0);
        return wallet(sb,bot).toString();
    }

    /** withdrawCash <0..CREDITS_MAX>: money.withdraw, at most the bank balance. */
    public String withdrawCash(String value) throws InterruptedException {
        Object[] q=request(value,"withdrawCash",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Integer amount=bounded(args[0],CREDITS_RE,0,CREDITS_MAX);
        if(amount==null) return invalidArgs("credits");
        if(amount>getBankBalance(bot)) return fail("refused reason=not-enough-bank bank="+getBankBalance(bot));
        String cap=creditCap((long)getCashBalance(bot)+getBankBalance(bot));
        if(cap!=null) return fail(cap);
        boolean ok=amount==0 || money.withdraw(bot,amount);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"amount",amount);kv(sb,"pending",amount!=0);
        return wallet(sb,bot).toString();
    }

    // ------------------------------------------------------------------
    // Faction
    // ------------------------------------------------------------------

    /**
     * setFaction <Imperial|Rebel|Neutral>: the engine calls factions.joinFaction
     * and the resignation path use: neutral and unaligned, or aligned to the
     * table's pvpFaction and covert.
     */
    public String setFaction(String value) throws InterruptedException {
        Object[] q=request(value,"setFaction",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        int i=pick(args[0],ALIGNED);
        if(i<0) return invalidArgs("faction");
        int hash=0;
        if(!"Neutral".equals(args[0])) {
            int row=factions.getFactionNumber(args[0]);
            hash=row<0?0:dataTableGetInt(factions.FACTION_TABLE,row,"pvpFaction");
            if(hash==0) return fail("refused reason=no-pvp-faction faction="+enc(args[0]));
        }
        rememberFaction(bot);
        pvpMakeNeutral(bot);
        pvpSetAlignedFaction(bot,hash);
        if(hash!=0) pvpMakeCovert(bot);
        StringBuilder sb=start(pvpGetAlignedFaction(bot)==hash?"ok":"refused");
        kv(sb,"faction",factionName(bot));kv(sb,"faction_id",pvpGetAlignedFaction(bot));kv(sb,"pvp_type",pvpName(pvpGetType(bot)));
        return sb.toString();
    }

    /** setStanding <faction> <-5000..50000>: factions.setFactionStanding (the library clamps to the rank cap). */
    public String setStanding(String value) throws InterruptedException {
        Object[] q=request(value,"setStanding",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String f=args[0];
        Float v=args[1].matches(STANDING_RE)?num(args[1],STANDING_MIN,STANDING_MAX):null;
        if(f==null || !f.matches(FACTION_RE) || v==null) return invalidArgs("setStanding");
        if(!playerFaction(f)) return fail("refused reason=not-player-faction faction="+enc(f));
        if(!hasObjVar(bot,RESET_ROOT+".standing."+f)) setObjVar(bot,RESET_ROOT+".standing."+f,factions.getFactionStanding(bot,f));
        factions.setFactionStanding(bot,f,v);
        StringBuilder sb=start("ok");
        kv(sb,"faction",f);kv(sb,"requested",v);kv(sb,"standing",factions.getFactionStanding(bot,f));
        return sb.toString();
    }

    /** setPvpType <neutral|covert|declared|onleave>: pvpMake*; anything but neutral needs an aligned faction. */
    public String setPvpType(String value) throws InterruptedException {
        Object[] q=request(value,"setPvpType",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        int i=pick(args[0],PVP_TYPES);
        if(i<0) return invalidArgs("pvpType");
        if(i>0 && pvpGetAlignedFaction(bot)==0) return fail("refused reason=no-faction use=setFaction");
        rememberFaction(bot);
        if(i==0) pvpMakeNeutral(bot);
        else if(i==1) pvpMakeCovert(bot);
        else if(i==2) pvpMakeDeclared(bot);
        else pvpMakeOnLeave(bot);
        StringBuilder sb=start("ok");
        kv(sb,"requested",args[0]);kv(sb,"pvp_type",pvpName(pvpGetType(bot)));kv(sb,"faction",factionName(bot));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Buffs
    // ------------------------------------------------------------------

    /** applyBuff <name> <1..BUFF_SECONDS_MAX s>: buff.applyBuff for an allowed buff (allowedBuff) the buff table knows; recorded for resetCharacter. */
    public String applyBuff(String value) throws InterruptedException {
        Object[] q=request(value,"applyBuff",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String n=name(args[0]);
        Integer seconds=bounded(args[1],SECONDS_RE,1,BUFF_SECONDS_MAX);
        if(n==null || seconds==null) return invalidArgs("applyBuff");
        if(!allowedBuff(n)) return fail("refused reason=buff-not-allowed buff="+n);
        if(buff.getBuffNameFromCrc(getStringCrc(n))==null) return fail("refused reason=unknown-buff buff="+n);
        boolean ok=buff.applyBuff(bot,n,seconds.floatValue());
        if(ok) setObjVar(bot,RESET_ROOT+".buff."+n,1);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"buff",n);kv(sb,"has",buff.hasBuff(bot,n));kv(sb,"seconds_left",String.format(java.util.Locale.ROOT,"%.1f",buff.getBuffTimeRemaining(bot,n)));
        return sb.toString();
    }

    /** removeBuff <name>: buff.removeBuff; removed=false when the bot did not have it. */
    public String removeBuff(String value) throws InterruptedException {
        Object[] q=request(value,"removeBuff",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String n=name(args[0]);
        if(n==null) return invalidArgs("buffName");
        boolean had=buff.hasBuff(bot,n);
        boolean removed=had && buff.removeBuff(bot,n);
        if(removed) removeObjVar(bot,RESET_ROOT+".buff."+n);
        StringBuilder sb=start("ok");
        kv(sb,"buff",n);kv(sb,"had",had);kv(sb,"removed",removed);kv(sb,"has",buff.hasBuff(bot,n));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Equipment and inventory
    // ------------------------------------------------------------------

    /** equipItem <itemOid>: equip of an item directly in the bot's inventory. */
    public String equipItem(String value) throws InterruptedException {
        Object[] q=request(value,"equipItem",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id item=oid(args[0]);
        if(item==null) return invalidArgs("itemOid");
        String s=scope(bot,item,false);
        if(s!=null) return fail(s);
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        if(!inventory.equals(getContainedBy(item))) return fail("out-of-scope reason=not-in-inventory object="+item);
        boolean ok=equip(item,bot);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"item",item);kv(sb,"template",getTemplateName(item));kv(sb,"worn",bot.equals(getContainedBy(item)));
        return sb.toString();
    }

    /** unequipItem <itemOid>: puts an item the bot wears back into its inventory. */
    public String unequipItem(String value) throws InterruptedException {
        Object[] q=request(value,"unequipItem",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id item=oid(args[0]);
        if(item==null) return invalidArgs("itemOid");
        String s=scope(bot,item,false);
        if(s!=null) return fail(s);
        if(!bot.equals(getContainedBy(item))) return fail("out-of-scope reason=not-worn object="+item);
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        boolean ok=putIn(item,inventory);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"item",item);kv(sb,"worn",bot.equals(getContainedBy(item)));
        return sb.toString();
    }

    /**
     * giveStaticCount <scenario> <name> <1..25>: creates that many copies of
     * one master_item static item in the bot's inventory. Like the scenario
     * family's creating ops it needs that scenario open on the bot, counts
     * against its cap (mayCreate) and tags and records each item (tag), so
     * the scenario family's scenarioEnd removes them; an item that cannot be
     * tagged is destroyed again.
     */
    public String giveStaticCount(String value) throws InterruptedException {
        Object[] q=request(value,"giveStaticCount",3,3);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String scenario=args[0];
        if(scenario==null || !scenario.matches(SCENARIO_RE)) return invalidArgs("scenario");
        String n=name(args[1]);
        Integer count=bounded(args[2],COUNT_RE,1,GIVE_COUNT_MAX);
        if(n==null || count==null) return invalidArgs("giveStaticCount");
        String s=mayCreate(bot,scenario,count);
        if(s!=null) return fail(s);
        if(dataTableSearchColumnForString(n,"name",static_item.MASTER_ITEM_TABLE)<0) return fail("refused reason=unknown-static-item name="+n);
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        int created=0,failed=0;
        StringBuilder sb=start("ok");
        kv(sb,"scenario",scenario);kv(sb,"name",n);
        int[] rc=new int[2];
        for(int i=0;i<count;i++) {
            obj_id item=static_item.createNewItemFunction(n,inventory);
            if(tag(bot,item,scenario)) {created++;row(sb,rc,item);}
            else failed++;
        }
        kv(sb,"created",created);kv(sb,"failed",failed);
        return end(sb,rc);
    }

    // ------------------------------------------------------------------
    // Reset
    // ------------------------------------------------------------------

    /**
     * resetCharacter: undoes what this family's setters changed and can be
     * undone. Removes the buffs applyBuff applied (recorded under
     * fixture.r.buff); restores the aligned faction and pvp type recorded
     * before the first setFaction or setPvpType and every standing recorded
     * before the first setStanding of that faction; revives a dead or
     * incapacitated bot (pclib.resurrectPlayer) and stands it upright;
     * recalculates the pool maxima from level and skills
     * (skill.recalcPlayerPools, which undoes setMaxHealth/setMaxAction) and
     * fills health and action; removes the fixture.t.* test objvars, the
     * fixture.snapshot.* snapshots and the fixture.r.* record. It cannot undo
     * level, profession, skills, expertise, credits, items, quests or buffs
     * the fixture did not apply, and it leaves an open scenario alone.
     */
    public String resetCharacter(String value) throws InterruptedException {
        Object[] q=request(value,"resetCharacter",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        int buffs=0,standings=0;
        obj_var_list applied=getObjVarList(bot,RESET_ROOT+".buff");
        if(applied!=null) for(int i=0;i<applied.getNumItems();i++) {
            obj_var v=applied.getObjVar(i);
            String n=v==null?null:name(v.getName());
            if(n!=null && buff.hasBuff(bot,n) && buff.removeBuff(bot,n)) buffs++;
        }
        obj_var_list stood=getObjVarList(bot,RESET_ROOT+".standing");
        if(stood!=null) for(int i=0;i<stood.getNumItems();i++) {
            obj_var v=stood.getObjVar(i);
            if(v==null || !playerFaction(v.getName()) || !(v.getData() instanceof Float)) continue;
            factions.setFactionStanding(bot,v.getName(),((Float)v.getData()).floatValue());
            standings++;
        }
        boolean faction=hasObjVar(bot,RESET_ROOT+".faction");
        if(faction) {
            int hash=getIntObjVar(bot,RESET_ROOT+".faction");
            int type=hasObjVar(bot,RESET_ROOT+".pvp")?getIntObjVar(bot,RESET_ROOT+".pvp"):PVPTYPE_NEUTRAL;
            pvpMakeNeutral(bot);
            pvpSetAlignedFaction(bot,hash);
            if(hash!=0 && type==PVPTYPE_COVERT) pvpMakeCovert(bot);
            else if(hash!=0 && type==PVPTYPE_DECLARED) pvpMakeDeclared(bot);
        }
        boolean down=isDead(bot) || isIncapacitated(bot);
        if(down) pclib.resurrectPlayer(bot);
        setPostureClientImmediate(bot,POSTURE_UPRIGHT);
        skill.recalcPlayerPools(bot,true);
        setAttrib(bot,HEALTH,getMaxAttrib(bot,HEALTH));
        setAttrib(bot,ACTION,getMaxAttrib(bot,ACTION));
        boolean vars=hasObjVar(bot,TEST_VAR_ROOT),snapshots=hasObjVar(bot,SNAPSHOT_ROOT);
        removeObjVar(bot,TEST_VAR_ROOT);
        removeObjVar(bot,SNAPSHOT_ROOT);
        removeObjVar(bot,RESET_ROOT);
        StringBuilder sb=start(isDead(bot) || isIncapacitated(bot)?"refused":"ok");
        kv(sb,"buffs_removed",buffs);kv(sb,"standings_restored",standings);kv(sb,"faction_restored",faction);
        kv(sb,"was_down",down);kv(sb,"test_vars_cleared",vars);kv(sb,"snapshots_cleared",snapshots);
        return sheet(sb,bot).toString();
    }
}
