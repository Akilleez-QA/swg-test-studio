package script.fixture;
import script.*;
import script.library.*;

/**
 * Multi-bot fixture family (op family "multi" of the agent fixture): ops
 * that involve a second registered fixture bot, so that several concurrent
 * test clients on different accounts can be arranged and asserted from the
 * server side (grouping, secure trade, account-to-account facts).
 *
 * Invoked through the CentralServer console:
 *   game <serverId> runScript fixture.agent_multi <method> <oid>:<stationId>:<characterName> [typed args...]
 *
 * The second bot arrives as its own identity triple (the runner replaces
 * the suite's role name with it). partner() checks that triple exactly the
 * way request() checks the acting bot: same regexes, loaded and
 * authoritative on this game server, a player with that exact full name
 * and unsigned station id, and not god. Any other player is refused, and so
 * is the acting bot itself. The guard and helpers below are copied verbatim
 * from agent_fixture.java (a test keeps them textually identical).
 *
 * No free-form command execution, no script attach/detach, no
 * sendConsoleCommand, no template creation. The class has no nested or
 * anonymous classes (and no lambdas) so it deploys as a single .class file.
 */
public class agent_multi extends base_script {
    private static final String P="agent_multi=";
    private static final int MAX_ROWS=200;
    private static final float SCOPE_RANGE=256.0f;
    private static final int CHAIN_MAX=64;
    private static final String OID_RE="[1-9][0-9]{0,18}";
    private static final String NUM_RE="-?[0-9]{1,5}(\\.[0-9]{1,6})?";
    private static final String INT_RE="-?[0-9]{1,9}";
    // Family argument kinds (swg_test_studio/fixture_ops/multi.py TYPES and RANGES).
    private static final String OFFSET_RE="[0-9]{1,2}(\\.[0-9]{1,2})?";
    private static final float BRING_OFFSET_MIN=0.5f;
    private static final float BRING_OFFSET_MAX=16.0f;
    private static final float BRING_OFFSET_DEFAULT=2.0f;
    private static final String SNAPSHOT_RE="[a-z][a-z0-9_]{0,23}";
    private static final String AMOUNT_RE="[1-9][0-9]{0,6}";
    private static final int PAY_MAX=1000000;
    // Cash plus bank a bot may hold after payTo (agent_character.java CREDITS_MAX).
    private static final int CREDITS_MAX=10000000;
    // Snapshots live on the bot itself under this objvar tree, one subtree per name; one
    // snapshot stores at most this many object ids in a single objvar array.
    private static final String SNAPSHOT_VAR="fixture.snapshot.";
    private static final int SNAPSHOT_ITEMS_MAX=100;
    // Objects a fixture op created carry this objvar (agent_scenario.java TAG_SCENARIO).
    private static final String TAG_SCENARIO="fixture.scenario";
    // At most this many object ids are listed in one *_ids reply field.
    private static final int IDS_MAX=32;

    // ------------------------------------------------------------------
    // Guard: environment, identity, arguments (verbatim from agent_fixture)
    // ------------------------------------------------------------------

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

    // ------------------------------------------------------------------
    // Scope: what the bot may touch (verbatim from agent_fixture)
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
    // Output (verbatim from agent_fixture, with this class's prefix P)
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
    // The second bot
    // ------------------------------------------------------------------

    /**
     * The other registered fixture bot named by an identity triple, checked
     * exactly as request() checks the acting bot. Returns {error-or-null,
     * partner}. Never the acting bot itself.
     */
    private Object[] partner(obj_id bot,String identity) throws InterruptedException {
        if(identity==null) return new Object[]{"invalid-args reason=partner",null};
        String[] fields=identity.split(":",-1);
        if(fields.length!=3 || !fields[0].matches("[1-9][0-9]{0,18}") ||
                !fields[1].matches("[1-9][0-9]{0,9}") || !fields[2].matches("Cap[a-z]{12}"))
            return new Object[]{"invalid-args reason=partner",null};
        long id,station;
        try {id=Long.parseLong(fields[0]);station=Long.parseLong(fields[1]);}
        catch(NumberFormatException e) {return new Object[]{"invalid-args reason=partner",null};}
        obj_id p=obj_id.getObjId(id);
        if(!isIdValid(p) || !p.isAuthoritative() || !exists(p)) return new Object[]{"out-of-scope reason=partner-not-here",null};
        if(!isPlayer(p) || !fields[2].equals(getPlayerFullName(p)) ||
                Integer.toUnsignedLong(getPlayerStationId(p))!=station || isGod(p))
            return new Object[]{"invalid-identity reason=partner",null};
        if(p.equals(bot)) return new Object[]{"invalid-args reason=partner-is-self",null};
        return new Object[]{null,p};
    }

    /** The identity triple of a checked bot, as the runner writes it. */
    private static String identityOf(obj_id who) throws InterruptedException {
        return who+":"+Integer.toUnsignedLong(getPlayerStationId(who))+":"+getPlayerFullName(who);
    }

    /** Null when a cash plus bank total stays within CREDITS_MAX, else a refusal. */
    private static String creditCap(long total) {
        return total>CREDITS_MAX?"refused reason=credits-cap total="+total+" cap="+CREDITS_MAX:null;
    }

    /**
     * True when the item's containment chain reaches the bot through the
     * bot's inventory container: carried in the inventory (or a bag in it),
     * not worn and not in the datapad, bank or mission bag.
     */
    private static boolean inInventory(obj_id bot,obj_id item) throws InterruptedException {
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory) || item.equals(inventory)) return false;
        obj_id c=getContainedBy(item);
        for(int i=0;i<CHAIN_MAX && isIdValid(c);i++) {
            if(c.equals(inventory)) return bot.equals(getContainedBy(inventory));
            if(c.equals(bot) || isPlayer(c)) return false;
            c=getContainedBy(c);
        }
        return false;
    }

    /** True when the item or anything inside it was created by a fixture op (tagged fixture.scenario). */
    private static boolean fixtureCreated(obj_id item) throws InterruptedException {
        if(hasObjVar(item,TAG_SCENARIO)) return true;
        obj_id[] inside=utils.getContents(item,true);
        if(inside!=null) for(obj_id x:inside) if(isIdValid(x) && hasObjVar(x,TAG_SCENARIO)) return true;
        return false;
    }

    private static String who(obj_id x,obj_id bot,obj_id other) {
        if(!isIdValid(x)) return "none";
        if(x.equals(bot)) return "bot";
        if(other!=null && x.equals(other)) return "partner";
        return "other";
    }

    /** Object ids of everything a bot carries or wears (recursive); null when more than SNAPSHOT_ITEMS_MAX. */
    private static java.util.TreeSet<Long> carried(obj_id who) throws InterruptedException {
        java.util.TreeSet<Long> ids=new java.util.TreeSet<Long>();
        obj_id[] all=utils.getContents(who,true);
        if(all!=null) for(obj_id x:all) if(isIdValid(x)) ids.add(x.getValue());
        return ids.size()>SNAPSHOT_ITEMS_MAX?null:ids;
    }

    private static String joinIds(java.util.Set<Long> ids) {
        StringBuilder b=new StringBuilder();
        int n=0;
        for(Long v:ids) {
            if(n>=IDS_MAX) break;
            b.append(n==0?"":",").append(v);
            n++;
        }
        return b.toString();
    }

    private static java.util.TreeSet<Long> minus(java.util.Set<Long> a,java.util.Set<Long> b) {
        java.util.TreeSet<Long> out=new java.util.TreeSet<Long>(a);
        out.removeAll(b);
        return out;
    }

    /** Stores cash, bank and carried object ids of one bot under the snapshot name; null or an error status. */
    private static String snapshotTake(obj_id who,String snap) throws InterruptedException {
        java.util.TreeSet<Long> ids=carried(who);
        if(ids==null) return "refused reason=too-many-items";
        String base=SNAPSHOT_VAR+snap;
        removeObjVar(who,base);
        obj_id[] items=new obj_id[ids.size()];
        int i=0;
        for(Long v:ids) items[i++]=obj_id.getObjId(v);
        boolean ok=setObjVar(who,base+".cash",getCashBalance(who)) && setObjVar(who,base+".bank",getBankBalance(who)) &&
                setObjVar(who,base+".count",items.length);
        if(ok && items.length>0) ok=setObjVar(who,base+".items",items);
        return ok?null:"refused reason=objvar";
    }

    /** {cashBefore, bankBefore} and the stored ids of one bot's snapshot, or null when absent. */
    private static Object[] snapshotRead(obj_id who,String snap) throws InterruptedException {
        String base=SNAPSHOT_VAR+snap;
        if(!hasObjVar(who,base+".cash") || !hasObjVar(who,base+".bank") || !hasObjVar(who,base+".count")) return null;
        java.util.TreeSet<Long> ids=new java.util.TreeSet<Long>();
        int count=getIntObjVar(who,base+".count");
        if(count>0) {
            obj_id[] items=getObjIdArrayObjVar(who,base+".items");
            if(items==null || items.length!=count) return null;
            for(obj_id x:items) if(x!=null) ids.add(x.getValue());
        }
        return new Object[]{(long)getIntObjVar(who,base+".cash"),(long)getIntObjVar(who,base+".bank"),ids};
    }

    // ------------------------------------------------------------------
    // Placement
    // ------------------------------------------------------------------

    /**
     * bring <partner> [offsetMeters 0.5..16, default 2]: moves the other bot
     * next to the acting bot (along +x, in the same cell when the bot is
     * indoors, on the terrain height outdoors). Both bots must be in the same
     * scene; space scenes are refused, and so is a partner that is dead,
     * incapacitated or in combat.
     */
    public String bring(String value) throws InterruptedException {
        Object[] q=request(value,"bring",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        Float offset=BRING_OFFSET_DEFAULT;
        if(args.length==2) {
            offset=args[1].matches(OFFSET_RE)?num(args[1],BRING_OFFSET_MIN,BRING_OFFSET_MAX):null;
            if(offset==null) return invalidArgs("offset");
        }
        if(isDead(other) || isIncapacitated(other)) return fail("refused reason=partner-down");
        if(getState(other,STATE_COMBAT)!=0) return fail("refused reason=partner-in-combat");
        String scene=getCurrentSceneName();
        if(scene==null || scene.startsWith("space_")) return fail("refused reason=space-scene scene="+enc(scene));
        location here=getLocation(bot),bw=getWorldLocation(bot),pw=getWorldLocation(other);
        if(here==null || bw==null || pw==null || pw.area==null || !pw.area.equals(bw.area))
            return fail("out-of-scope reason=partner-scene");
        location target;
        if(isIdValid(here.cell)) target=new location(here.x+offset,here.y,here.z,here.area,here.cell);
        else target=new location(here.x+offset,getHeightAtLocation(here.x+offset,here.z),here.z,here.area);
        boolean moved=setLocation(other,target);
        StringBuilder sb=start(moved?"ok":"refused");
        kv(sb,"partner",other);kv(sb,"scene",scene);kv(sb,"offset",offset);
        kv(sb,"cell",isIdValid(here.cell)?here.cell:"none");
        kv(sb,"distance",String.format(java.util.Locale.ROOT,"%.1f",getDistance(bot,other)));
        return sb.toString();
    }

    /** distanceTo <partner>: distance and whether both bots share scene, building and cell. */
    public String distanceTo(String value) throws InterruptedException {
        Object[] q=request(value,"distanceTo",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        location bw=getWorldLocation(bot),pw=getWorldLocation(other),bl=getLocation(bot),pl=getLocation(other);
        boolean sameScene=bw!=null && pw!=null && bw.area!=null && bw.area.equals(pw.area);
        obj_id bb=botBuilding(bot),pb=botBuilding(other);
        boolean sameCell=bl!=null && pl!=null && isIdValid(bl.cell) && bl.cell.equals(pl.cell);
        StringBuilder sb=start("ok");
        kv(sb,"partner",other);
        kv(sb,"distance",sameScene?String.format(java.util.Locale.ROOT,"%.1f",getDistance(bw,pw)):"none");
        kv(sb,"same_scene",sameScene);kv(sb,"bot_scene",bw==null?"none":bw.area);kv(sb,"partner_scene",pw==null?"none":pw.area);
        kv(sb,"same_building",bb!=null && bb.equals(pb));kv(sb,"same_cell",sameCell);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Groups
    // ------------------------------------------------------------------

    /**
     * groupOf [partner]: the acting bot's group: id, size, player size,
     * leader and who the leader is (bot, partner, other, none); with a
     * partner also its group and whether both share one. One row per
     * member: oid, name, who, identity (for the bot and the partner).
     */
    public String groupOf(String value) throws InterruptedException {
        Object[] q=request(value,"groupOf",0,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id other=null;
        if(args.length==1) {
            Object[] o=partner(bot,args[0]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        obj_id g=getGroupObject(bot);
        boolean grouped=isIdValid(g);
        obj_id leader=grouped?getGroupLeaderId(g):null;
        StringBuilder sb=start("ok");
        kv(sb,"group",grouped?g:"none");
        kv(sb,"size",grouped?getGroupSize(g):0);kv(sb,"pc_size",grouped?getPCGroupSize(g):0);
        kv(sb,"leader",isIdValid(leader)?leader:"none");kv(sb,"leader_is",who(leader,bot,other));
        if(other!=null) {
            obj_id pg=getGroupObject(other);
            kv(sb,"partner_group",isIdValid(pg)?pg:"none");
            kv(sb,"same_group",grouped && isIdValid(pg) && g.equals(pg));
        }
        int[] rc=new int[2];
        if(grouped) {
            obj_id[] members=getGroupMemberIds(g);
            String[] names=getGroupMemberNames(g);
            if(members!=null) for(int i=0;i<members.length;i++) {
                String w=who(members[i],bot,other);
                String n=names!=null && i<names.length?names[i]:"none";
                row(sb,rc,members[i],n,w,w.equals("bot")||w.equals("partner")?identityOf(members[i]):"none");
            }
        }
        return end(sb,rc);
    }

    /**
     * groupLeave [partner]: the acting bot, or the partner, leaves its group
     * through the server's own group library (a queued leaveGroup command:
     * assert the outcome with a later groupOf). Already solo: ok, queued=false,
     * so a suite can use it to arrange a solo start. Refused when the one
     * leaving leads a group of more than two that has a member other than
     * the bot and the named partner: leaving would hand leadership to a
     * player the fixture does not control.
     */
    public String groupLeave(String value) throws InterruptedException {
        Object[] q=request(value,"groupLeave",0,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id other=null;
        if(args.length==1) {
            Object[] o=partner(bot,args[0]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        obj_id target=other==null?bot:other;
        obj_id g=getGroupObject(target);
        boolean grouped=isIdValid(g);
        if(grouped && target.equals(getGroupLeaderId(g))) {
            obj_id[] members=getGroupMemberIds(g);
            if(members!=null && members.length>2) for(obj_id m:members)
                if(isIdValid(m) && !m.equals(bot) && !m.equals(other))
                    return fail("refused reason=would-hand-leadership member="+m);
        }
        if(grouped) group.leaveGroup(target);
        StringBuilder sb=start("ok");
        kv(sb,"who",target.equals(bot)?"bot":"partner");kv(sb,"group",grouped?g:"none");kv(sb,"queued",grouped);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Credits and accounts
    // ------------------------------------------------------------------

    /** creditsOf <partner>: the partner's cash, bank and total, and the acting bot's. */
    public String creditsOf(String value) throws InterruptedException {
        Object[] q=request(value,"creditsOf",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        StringBuilder sb=start("ok");
        kv(sb,"partner",other);
        kv(sb,"cash",getCashBalance(other));kv(sb,"bank",getBankBalance(other));kv(sb,"total",getTotalMoney(other));
        kv(sb,"bot_cash",getCashBalance(bot));kv(sb,"bot_bank",getBankBalance(bot));kv(sb,"bot_total",getTotalMoney(bot));
        return sb.toString();
    }

    /** accountOf <partner>: both station (account) ids and whether the bots share an account. */
    public String accountOf(String value) throws InterruptedException {
        Object[] q=request(value,"accountOf",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        long bs=Integer.toUnsignedLong(getPlayerStationId(bot)),ps=Integer.toUnsignedLong(getPlayerStationId(other));
        StringBuilder sb=start("ok");
        kv(sb,"bot_station",bs);kv(sb,"partner_station",ps);kv(sb,"same_account",bs==ps);
        kv(sb,"bot_name",getPlayerFullName(bot));kv(sb,"partner_name",getPlayerFullName(other));
        kv(sb,"partner_identity",identityOf(other));
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Secure trade (item flag only; see docs/fixture-multi.md)
    // ------------------------------------------------------------------

    /** tradeState [partner]: carried items flagged as in secure trade, for the bot and the partner. */
    public String tradeState(String value) throws InterruptedException {
        Object[] q=request(value,"tradeState",0,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id other=null;
        if(args.length==1) {
            Object[] o=partner(bot,args[0]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        int mine=0,theirs=0;
        obj_id[] all=utils.getContents(bot,true);
        if(all!=null) for(obj_id x:all) if(isIdValid(x) && isInSecureTrade(x)) {mine++;row(sb,rc,"bot",x,getTemplateName(x));}
        kv(sb,"bot_items_in_trade",mine);
        if(other!=null) {
            all=utils.getContents(other,true);
            if(all!=null) for(obj_id x:all) if(isIdValid(x) && isInSecureTrade(x)) {theirs++;row(sb,rc,"partner",x,getTemplateName(x));}
            kv(sb,"partner_items_in_trade",theirs);
        }
        return end(sb,rc);
    }

    // ------------------------------------------------------------------
    // Snapshot and diff (server-side assertion of a trade)
    // ------------------------------------------------------------------

    /**
     * snapshot <name> [partner]: records cash, bank and the ids of every
     * carried item (at most SNAPSHOT_ITEMS_MAX, 100) of the bot, and of the partner when given,
     * under objvar fixture.snapshot.<name> on each bot. Replaces an older
     * snapshot of that name.
     */
    public String snapshot(String value) throws InterruptedException {
        Object[] q=request(value,"snapshot",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String snap=args[0].matches(SNAPSHOT_RE)?args[0]:null;
        if(snap==null) return invalidArgs("snapshot-name");
        obj_id other=null;
        if(args.length==2) {
            Object[] o=partner(bot,args[1]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        String s=snapshotTake(bot,snap);
        if(s==null && other!=null) s=snapshotTake(other,snap);
        if(s!=null) return fail(s);
        StringBuilder sb=start("ok");
        kv(sb,"snapshot",snap);
        kv(sb,"items",getIntObjVar(bot,SNAPSHOT_VAR+snap+".count"));kv(sb,"cash",getCashBalance(bot));kv(sb,"bank",getBankBalance(bot));
        if(other!=null) {
            kv(sb,"partner_items",getIntObjVar(other,SNAPSHOT_VAR+snap+".count"));
            kv(sb,"partner_cash",getCashBalance(other));kv(sb,"partner_bank",getBankBalance(other));
        }
        return sb.toString();
    }

    /**
     * diff <name> [partner]: what changed since snapshot <name>. For the bot:
     * gained, lost, cash_delta, bank_delta and the first 32 ids of each.
     * With a partner also its changes and the cross-checks of a trade:
     * moved_to_partner, moved_from_partner, duplicated (carried by both now),
     * items_conserved (every item that left one bot is carried by the other,
     * and nothing new appeared) and credits_conserved (the four deltas sum to 0).
     */
    public String diff(String value) throws InterruptedException {
        Object[] q=request(value,"diff",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String snap=args[0].matches(SNAPSHOT_RE)?args[0]:null;
        if(snap==null) return invalidArgs("snapshot-name");
        obj_id other=null;
        if(args.length==2) {
            Object[] o=partner(bot,args[1]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        Object[] mine=snapshotRead(bot,snap);
        if(mine==null) return fail("refused reason=no-snapshot who=bot snapshot="+enc(snap));
        Object[] theirs=null;
        if(other!=null) {
            theirs=snapshotRead(other,snap);
            if(theirs==null) return fail("refused reason=no-snapshot who=partner snapshot="+enc(snap));
        }
        java.util.TreeSet<Long> botNow=carried(bot);
        if(botNow==null) return fail("refused reason=too-many-items who=bot");
        @SuppressWarnings("unchecked") java.util.Set<Long> botBefore=(java.util.Set<Long>)mine[2];
        java.util.TreeSet<Long> gained=minus(botNow,botBefore),lost=minus(botBefore,botNow);
        long cashDelta=getCashBalance(bot)-(Long)mine[0],bankDelta=getBankBalance(bot)-(Long)mine[1];
        StringBuilder sb=start("ok");
        kv(sb,"snapshot",snap);
        kv(sb,"gained",gained.size());kv(sb,"lost",lost.size());
        kv(sb,"cash_delta",cashDelta);kv(sb,"bank_delta",bankDelta);
        kv(sb,"gained_ids",joinIds(gained));kv(sb,"lost_ids",joinIds(lost));
        int[] rc=new int[2];
        for(Long v:lost) row(sb,rc,"lost",v);
        for(Long v:gained) row(sb,rc,"gained",v,getTemplateName(obj_id.getObjId(v)));
        if(other!=null) {
            java.util.TreeSet<Long> otherNow=carried(other);
            if(otherNow==null) return fail("refused reason=too-many-items who=partner");
            @SuppressWarnings("unchecked") java.util.Set<Long> otherBefore=(java.util.Set<Long>)theirs[2];
            java.util.TreeSet<Long> pGained=minus(otherNow,otherBefore),pLost=minus(otherBefore,otherNow);
            long pCash=getCashBalance(other)-(Long)theirs[0],pBank=getBankBalance(other)-(Long)theirs[1];
            java.util.TreeSet<Long> toPartner=new java.util.TreeSet<Long>(lost);toPartner.retainAll(pGained);
            java.util.TreeSet<Long> fromPartner=new java.util.TreeSet<Long>(pLost);fromPartner.retainAll(gained);
            java.util.TreeSet<Long> both=new java.util.TreeSet<Long>(botNow);both.retainAll(otherNow);
            java.util.TreeSet<Long> left=new java.util.TreeSet<Long>(lost);left.addAll(pLost);
            java.util.TreeSet<Long> arrived=new java.util.TreeSet<Long>(gained);arrived.addAll(pGained);
            kv(sb,"partner_gained",pGained.size());kv(sb,"partner_lost",pLost.size());
            kv(sb,"partner_cash_delta",pCash);kv(sb,"partner_bank_delta",pBank);
            kv(sb,"moved_to_partner",toPartner.size());kv(sb,"moved_from_partner",fromPartner.size());
            kv(sb,"moved_to_partner_ids",joinIds(toPartner));kv(sb,"moved_from_partner_ids",joinIds(fromPartner));
            kv(sb,"duplicated",both.size());
            kv(sb,"items_conserved",left.equals(arrived) && both.isEmpty());
            kv(sb,"credits_conserved",cashDelta+bankDelta+pCash+pBank==0);
            for(Long v:pLost) row(sb,rc,"partner_lost",v);
            for(Long v:pGained) row(sb,rc,"partner_gained",v,getTemplateName(obj_id.getObjId(v)));
        }
        return end(sb,rc);
    }

    /** snapshotDrop <name> [partner]: removes the snapshot objvars from the bot (and the partner). */
    public String snapshotDrop(String value) throws InterruptedException {
        Object[] q=request(value,"snapshotDrop",1,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String snap=args[0].matches(SNAPSHOT_RE)?args[0]:null;
        if(snap==null) return invalidArgs("snapshot-name");
        obj_id other=null;
        if(args.length==2) {
            Object[] o=partner(bot,args[1]);
            if(o[0]!=null) return fail((String)o[0]);
            other=(obj_id)o[1];
        }
        boolean had=hasObjVar(bot,SNAPSHOT_VAR+snap);
        removeObjVar(bot,SNAPSHOT_VAR+snap);
        boolean partnerHad=false;
        if(other!=null) {
            partnerHad=hasObjVar(other,SNAPSHOT_VAR+snap);
            removeObjVar(other,SNAPSHOT_VAR+snap);
        }
        StringBuilder sb=start("ok");
        kv(sb,"snapshot",snap);kv(sb,"removed",had);
        if(other!=null) kv(sb,"partner_removed",partnerHad);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Transfers between the two bots (arranging)
    // ------------------------------------------------------------------

    /**
     * giveTo <partner> <itemOid>: moves an item the acting bot carries in its
     * inventory (its containment chain goes through the inventory container:
     * not worn, not in the datapad, bank or mission bag; not in a secure
     * trade) into the partner's inventory. Refused for an item a fixture op
     * created, or one holding such an item: it belongs to the giver's open
     * scenario, whose scenarioEnd could no longer reach it.
     */
    public String giveTo(String value) throws InterruptedException {
        Object[] q=request(value,"giveTo",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        obj_id item=oid(args[1]);
        if(item==null) return invalidArgs("itemOid");
        String s=scope(bot,item,false);
        if(s!=null) return fail(s);
        if(!inInventory(bot,item)) return fail("out-of-scope reason=not-in-inventory object="+item);
        if(fixtureCreated(item)) return fail("refused reason=fixture-created object="+item);
        if(isInSecureTrade(item)) return fail("refused reason=in-trade object="+item);
        obj_id target=utils.getInventoryContainer(other);
        if(!isIdValid(target)) return fail("refused reason=no-inventory who=partner");
        boolean ok=putIn(item,target);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"object",item);kv(sb,"partner",other);kv(sb,"container",getContainedBy(item));
        return sb.toString();
    }

    /**
     * payTo <partner> <amount 1..1000000>: transfers cash from the acting bot
     * to the partner through the money library (asynchronous: assert with a
     * later creditsOf or diff). Refused when the bot has too little cash or
     * the partner's cash plus bank would exceed CREDITS_MAX.
     */
    public String payTo(String value) throws InterruptedException {
        Object[] q=request(value,"payTo",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Object[] o=partner(bot,args[0]);
        if(o[0]!=null) return fail((String)o[0]);
        obj_id other=(obj_id)o[1];
        Integer amount=args[1].matches(AMOUNT_RE)?integer(args[1],1,PAY_MAX):null;
        if(amount==null) return invalidArgs("amount");
        int cash=getCashBalance(bot);
        if(cash<amount) return fail("refused reason=insufficient-cash cash="+cash);
        String cap=creditCap((long)getCashBalance(other)+getBankBalance(other)+amount);
        if(cap!=null) return fail(cap);
        boolean requested=money.cashTo(bot,other,amount);
        StringBuilder sb=start(requested?"ok":"refused");
        kv(sb,"partner",other);kv(sb,"amount",amount);kv(sb,"requested",requested);
        kv(sb,"bot_cash_before",cash);kv(sb,"partner_cash_before",getCashBalance(other));
        return sb.toString();
    }
}
