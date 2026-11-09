package script.fixture;
import script.*;
import script.library.*;

/**
 * Arrange/assert fixture for dedicated protocol bots in labelled copied
 * schemas only; never a role image. Ported from our personal-play console
 * script (developer.claude.cli) with its god-character trust removed.
 *
 * Invoked through the CentralServer console:
 *   game <serverId> runScript fixture.agent_fixture <method> <oid>:<stationId>:<characterName> [typed args...]
 *
 * Every public method: (1) refuses outside an isolation fixture with a
 * WGC_ schema, (2) authenticates the exact non-god bot identity on its
 * authoritative server (otherwise "not-here" so the caller tries the next
 * game server), (3) parses typed arguments with strict allow-lists, (4)
 * acts only on objects near or inside the bot / the bot's building and
 * never on another player or anything another player carries, and (5)
 * answers one line "agent_fixture=<status> key=value ...".
 *
 * No free-form command execution, no script attach/detach, no
 * sendConsoleCommand, no arbitrary template creation. The class has no
 * nested classes so it deploys as a single .class file.
 */
public class agent_fixture extends base_script {
    private static final String P="agent_fixture=";
    private static final int MAX_ROWS=200;
    private static final float SCOPE_RANGE=256.0f;
    private static final float NEARBY_MAX=128.0f;
    private static final int CHAIN_MAX=64;
    private static final String OID_RE="[1-9][0-9]{0,18}";
    private static final String NUM_RE="-?[0-9]{1,5}(\\.[0-9]{1,6})?";
    private static final String INT_RE="-?[0-9]{1,9}";
    private static final String NAME_RE="[a-z0-9_]{1,64}";
    private static final String CELL_RE="[A-Za-z0-9_]{1,64}";
    private static final String DECOR_TAG_VAR="claude.decor";
    private static final int CLEAR_DECOR_MAX=500;
    private static final String EXPERTISE_TABLE="datatables/expertise/expertise.iff";
    private static final int EXPERTISE_TEST_TREE=99;
    private static final String SKILLS_TABLE="datatables/skill/skills.iff";
    private static final String COLLECTION_TABLE="datatables/collection/collection.iff";
    private static final String[] PLAYER_COLLECTION_BOOKS={
        "achievement_book","armor_book","artifact_book","badge_book","crafting_book",
        "decor_book","device_book","hobbies_book","neutral_faction_mercenary_book",
        "saga_relic_book","slayer_book","space_book_01","space_book_02","weapon_book"
    };
    // Compiled draft schematic templates, tried in order. The first is the
    // path developer.claude.cli used; the others are relative to the game
    // server working directory of a standard swg-main checkout.
    private static final String[] DRAFT_SCHEMATIC_DIRS={
        "/opt/whitengold/data/sku.0/sys.server/compiled/game/object/draft_schematic",
        "/home/swg/swg-main/data/sku.0/sys.server/compiled/game/object/draft_schematic",
        "../../data/sku.0/sys.server/compiled/game/object/draft_schematic",
        "data/sku.0/sys.server/compiled/game/object/draft_schematic"
    };
    private static final int SCHEMATIC_FILE_MAX=50000;

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
    /** scope() plus: never a player (not even the bot), never a cell. For mutating methods. */
    private static String movable(obj_id bot,obj_id o) throws InterruptedException {
        String s=scope(bot,o,false);
        if(s!=null) return s;
        if(isPlayer(o)) return "out-of-scope reason=player object="+o;
        String t=getTemplateName(o);
        if(t==null || t.startsWith("object/cell/")) return "out-of-scope reason=cell object="+o;
        return null;
    }

    /** Cell-local location in a building; null when the cell is absent. */
    private static location cellLocation(obj_id building,String cell,float x,float y,float z) throws InterruptedException {
        obj_id c=getCellId(building,cell);
        location b=getLocation(building);
        if(!isIdValid(c) || b==null) return null;
        return new location(x,y,z,b.area,c);
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
    // Inspect (read-only)
    // ------------------------------------------------------------------

    /** inspect: where the bot is (world and cell-local), level, profession. */
    public String inspect(String value) throws InterruptedException {
        Object[] q=request(value,"inspect",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        location l=getLocation(bot),w=getWorldLocation(bot);
        obj_id building=botBuilding(bot);
        boolean inside=l!=null && isIdValid(l.cell);
        StringBuilder sb=start("ok");
        kv(sb,"player",bot);kv(sb,"scene",getCurrentSceneName());
        kv(sb,"world_x",w==null?Float.NaN:w.x);kv(sb,"world_y",w==null?Float.NaN:w.y);kv(sb,"world_z",w==null?Float.NaN:w.z);
        kv(sb,"yaw",getYaw(bot));
        kv(sb,"building",inside&&building!=null?building:"none");
        kv(sb,"building_template",inside&&building!=null?getTemplateName(building):"none");
        kv(sb,"cell",inside?l.cell:"none");kv(sb,"cell_name",inside?getCellName(l.cell):"none");
        kv(sb,"x",inside?(Object)l.x:"none");kv(sb,"y",inside?(Object)l.y:"none");kv(sb,"z",inside?(Object)l.z:"none");
        kv(sb,"level",getLevel(bot));kv(sb,"profession",getSkillTemplate(bot));kv(sb,"god",isGod(bot));
        return sb.toString();
    }

    /** nearby <radiusMeters<=128>: objects around the bot: oid, distance, template. */
    public String nearby(String value) throws InterruptedException {
        Object[] q=request(value,"nearby",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Float radius=num(args[0],0.1f,NEARBY_MAX);
        if(radius==null) return invalidArgs("radius");
        obj_id[] objects=getObjectsInRange(getLocation(bot),radius);
        StringBuilder sb=kv(start("ok"),"radius",radius);
        int[] rc=new int[2];
        if(objects!=null) for(obj_id x:objects) {
            if(!isIdValid(x) || x.equals(bot)) continue;
            row(sb,rc,x,String.format("%.1f",getDistance(bot,x)),getTemplateName(x));
        }
        return end(sb,rc);
    }

    /** cells <buildingOid>: the building's cell names. */
    public String cells(String value) throws InterruptedException {
        Object[] q=request(value,"cells",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id building=oid(args[0]);
        if(building==null) return invalidArgs("buildingOid");
        String s=scope(bot,building,false);
        if(s!=null) return fail(s);
        String[] names=getCellNames(building);
        StringBuilder joined=new StringBuilder();
        if(names!=null) for(int i=0;i<names.length && i<MAX_ROWS;i++) joined.append(i==0?"":",").append(enc(names[i]));
        return P+"ok building="+building+" count="+(names==null?0:names.length)+" cells="+(joined.length()==0?"none":joined);
    }

    /** contents <buildingOid>: every object directly inside each cell: cell, oid, template. */
    public String contents(String value) throws InterruptedException {
        Object[] q=request(value,"contents",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id building=oid(args[0]);
        if(building==null) return invalidArgs("buildingOid");
        String s=scope(bot,building,false);
        if(s!=null) return fail(s);
        StringBuilder sb=kv(start("ok"),"building",building);
        int[] rc=new int[2];
        obj_id[] cells=getContents(building);
        if(cells!=null) for(obj_id cell:cells) {
            if(!isIdValid(cell)) continue;
            obj_id[] inside=getContents(cell);
            if(inside!=null) for(obj_id x:inside) if(isIdValid(x)) row(sb,rc,getCellName(cell),x,getTemplateName(x));
        }
        return end(sb,rc);
    }

    /** describe <objectOid>: template, container, objvar names, recursive contents. */
    public String describe(String value) throws InterruptedException {
        Object[] q=request(value,"describe",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        if(x==null) return invalidArgs("objectOid");
        String s=scope(bot,x,true);
        if(s!=null) return fail(s);
        StringBuilder sb=start("ok");
        kv(sb,"object",x);kv(sb,"template",getTemplateName(x));kv(sb,"container",getContainedBy(x));kv(sb,"name",getName(x));
        int[] rc=new int[2];
        obj_var_list vars=getObjVarList(x,"");
        if(vars!=null) for(int i=0;i<vars.getNumItems();i++) {
            obj_var v=vars.getObjVar(i);
            if(v!=null) row(sb,rc,"objvar",v.getName());
        }
        obj_id[] inner=utils.getContents(x,true);
        if(inner!=null) for(obj_id y:inner) if(isIdValid(y)) row(sb,rc,"contains",y,getTemplateName(y));
        return end(sb,rc);
    }

    /** items: everything the bot carries or wears (recursive): oid, template, container. */
    public String items(String value) throws InterruptedException {
        Object[] q=request(value,"items",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        obj_id[] all=utils.getContents(bot,true);
        if(all!=null) for(obj_id x:all) if(isIdValid(x)) row(sb,rc,x,getTemplateName(x),getContainedBy(x));
        return end(sb,rc);
    }

    /** structure <structureOid>: owner and whether the bot is owner/admin. */
    public String structure(String value) throws InterruptedException {
        Object[] q=request(value,"structure",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        if(x==null) return invalidArgs("structureOid");
        String s=scope(bot,x,false);
        if(s!=null) return fail(s);
        StringBuilder sb=start("ok");
        kv(sb,"structure",x);kv(sb,"template",getTemplateName(x));kv(sb,"owner",getOwner(x));
        kv(sb,"bot_is_owner",player_structure.isOwner(x,bot));kv(sb,"bot_is_admin",player_structure.isAdmin(x,bot));
        return sb.toString();
    }

    /** countIn <containerOid>: direct and recursive content counts, container type. */
    public String countIn(String value) throws InterruptedException {
        Object[] q=request(value,"countIn",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        if(x==null) return invalidArgs("containerOid");
        String s=scope(bot,x,true);
        if(s!=null) return fail(s);
        obj_id[] direct=getContents(x);
        obj_id[] deep=utils.getContents(x,true);
        StringBuilder sb=start("ok");
        kv(sb,"container",x);kv(sb,"direct",direct==null?-1:direct.length);
        kv(sb,"recursive",deep==null?-1:deep.length);kv(sb,"type",getContainerType(x));
        return sb.toString();
    }

    /**
     * tryPut <objectOid> <containerOid>: tries putIn and reports the volumes
     * and container types that explain a refusal. Mutates only on success
     * (developer.claude.cli semantics).
     */
    public String tryPut(String value) throws InterruptedException {
        Object[] q=request(value,"tryPut",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id item=oid(args[0]),box=oid(args[1]);
        if(item==null || box==null) return invalidArgs("oid");
        String s=movable(bot,item);
        if(s==null) s=scope(bot,box,true);
        if(s!=null) return fail(s);
        obj_id[] in=getContents(item);
        int itemVolume=getVolume(item),boxFree=getVolumeFree(box),boxType=getContainerType(box),itemType=getContainerType(item);
        boolean put=putIn(item,box);
        StringBuilder sb=start("ok");
        kv(sb,"result",put?"put":"refused");kv(sb,"item",item);kv(sb,"container",box);
        kv(sb,"item_volume",itemVolume);kv(sb,"item_contents",in==null?0:in.length);
        kv(sb,"box_free",boxFree);kv(sb,"box_type",boxType);kv(sb,"item_type",itemType);
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // Arrange (mutating)
    // ------------------------------------------------------------------

    /** place <buildingOid> <cellName> <x> <y> <z> <yawDeg>: puts the bot at a spot in a room (cli lookFrom). */
    public String place(String value) throws InterruptedException {
        Object[] q=request(value,"place",6,6);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id building=oid(args[0]);
        String cell=cellName(args[1]);
        Float x=num(args[2],-512,512),y=num(args[3],-512,512),z=num(args[4],-512,512),yaw=num(args[5],-360,360);
        if(building==null || cell==null || x==null || y==null || z==null || yaw==null) return invalidArgs("place");
        String s=scope(bot,building,false);
        if(s!=null) return fail(s);
        location target=cellLocation(building,cell,x,y,z);
        if(target==null) return fail("refused reason=no-such-cell");
        boolean moved=setLocation(bot,target);
        if(moved) setYaw(bot,yaw);
        StringBuilder sb=start(moved?"ok":"refused");
        kv(sb,"building",building);kv(sb,"cell",cell);kv(sb,"x",x);kv(sb,"y",y);kv(sb,"z",z);kv(sb,"yaw",getYaw(bot));
        return sb.toString();
    }

    /**
     * warp <x> <y> <z>: moves the bot to a world (outdoor) point in its
     * current scene. Interior-only scenes are refused; use place for rooms.
     */
    public String warp(String value) throws InterruptedException {
        Object[] q=request(value,"warp",3,3);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        Float x=num(args[0],-8192,8192),y=num(args[1],-1000,10000),z=num(args[2],-8192,8192);
        if(x==null || y==null || z==null) return invalidArgs("warp");
        String scene=getCurrentSceneName();
        if(scene==null || scene.startsWith("dungeon") || scene.startsWith("space_") || scene.startsWith("tutorial"))
            return fail("refused reason=interior-scene use=place scene="+enc(scene));
        boolean moved=setLocation(bot,new location(x,y,z,scene));
        location w=getWorldLocation(bot);
        StringBuilder sb=start(moved?"ok":"refused");
        kv(sb,"scene",scene);
        kv(sb,"world_x",w==null?Float.NaN:w.x);kv(sb,"world_y",w==null?Float.NaN:w.y);kv(sb,"world_z",w==null?Float.NaN:w.z);
        return sb.toString();
    }

    /** moveInto <objectOid> <buildingOid> <cellName> <x> <y> <z>: moves an object to a spot in a room. */
    public String moveInto(String value) throws InterruptedException {
        Object[] q=request(value,"moveInto",6,6);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]),building=oid(args[1]);
        String cell=cellName(args[2]);
        Float px=num(args[3],-512,512),py=num(args[4],-512,512),pz=num(args[5],-512,512);
        if(x==null || building==null || cell==null || px==null || py==null || pz==null) return invalidArgs("moveInto");
        String s=movable(bot,x);
        if(s==null) s=scope(bot,building,false);
        if(s!=null) return fail(s);
        location target=cellLocation(building,cell,px,py,pz);
        if(target==null) return fail("refused reason=no-such-cell");
        boolean moved=setLocation(x,target);
        StringBuilder sb=start(moved?"ok":"refused");
        kv(sb,"object",x);kv(sb,"building",building);kv(sb,"cell",cell);
        return sb.toString();
    }

    /**
     * transform <objectOid> <x> <z> <yawDeg>: moves an outdoor object
     * (including a building, which carries its contents) to a world point on
     * the terrain within 256 m of the bot and sets its facing.
     */
    public String transform(String value) throws InterruptedException {
        Object[] q=request(value,"transform",4,4);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        Float px=num(args[1],-8192,8192),pz=num(args[2],-8192,8192),yaw=num(args[3],-360,360);
        if(x==null || px==null || pz==null || yaw==null) return invalidArgs("transform");
        String s=movable(bot,x);
        if(s!=null) return fail(s);
        location target=getLocation(x);
        if(target==null || isIdValid(target.cell) || isIdValid(getContainedBy(x))) return fail("refused reason=not-outdoors object="+x);
        location b=getWorldLocation(bot);
        target.x=px;target.z=pz;target.y=getHeightAtLocation(px,pz);
        if(b==null || getDistance(target,b)>SCOPE_RANGE) return fail("out-of-scope reason=destination-distance");
        boolean moved=setLocation(x,target);
        if(moved) setYaw(x,yaw);
        location now=getLocation(x);
        StringBuilder sb=start(moved?"ok":"refused");
        kv(sb,"object",x);
        kv(sb,"x",now==null?Float.NaN:now.x);kv(sb,"y",now==null?Float.NaN:now.y);kv(sb,"z",now==null?Float.NaN:now.z);
        kv(sb,"yaw",getYaw(x));
        return sb.toString();
    }

    /**
     * setDown <buildingOid> <cellName> <x> <y> <z> <oid,oid,...>: sets items
     * on the floor of a room in a row along +x (1 m apart). At most 32 items.
     */
    public String setDown(String value) throws InterruptedException {
        Object[] q=request(value,"setDown",6,6);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id building=oid(args[0]);
        String cell=cellName(args[1]);
        Float px=num(args[2],-512,512),py=num(args[3],-512,512),pz=num(args[4],-512,512);
        String[] ids=list(args[5],OID_RE,32);
        if(building==null || cell==null || px==null || py==null || pz==null || ids==null) return invalidArgs("setDown");
        String s=scope(bot,building,false);
        if(s!=null) return fail(s);
        if(!isIdValid(getCellId(building,cell))) return fail("refused reason=no-such-cell");
        obj_id[] items=new obj_id[ids.length];
        for(int i=0;i<ids.length;i++) {
            items[i]=oid(ids[i]);
            if(items[i]==null) return invalidArgs("oid");
            s=movable(bot,items[i]);
            if(s!=null) return fail(s);
        }
        float x=px;
        int placed=0;
        StringBuilder sb=start("ok");
        kv(sb,"building",building);kv(sb,"cell",cell);
        int[] rc=new int[2];
        for(obj_id item:items) {
            location spot=cellLocation(building,cell,x,py,pz);
            boolean ok=spot!=null && setLocation(item,spot);
            if(ok) {x+=1.0f;placed++;}
            row(sb,rc,item,ok?"placed":"refused");
        }
        kv(sb,"placed",placed);
        return end(sb,rc);
    }

    /** scale <objectOid> <scale>: sets an object's scale (0.05..20). */
    public String scale(String value) throws InterruptedException {
        Object[] q=request(value,"scale",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        Float v=num(args[1],0.05f,20.0f);
        if(x==null || v==null) return invalidArgs("scale");
        String s=scope(bot,x,true);
        if(s!=null) return fail(s);
        boolean ok=setScale(x,v);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"object",x);kv(sb,"scale",getScale(x));
        return sb.toString();
    }

    /**
     * grantExpertise [treeId,...]: grants every expertise box (all ranks) in
     * the given trees, or all trees except the test tree, lowest tier and
     * rank first.
     */
    public String grantExpertise(String value) throws InterruptedException {
        Object[] q=request(value,"grantExpertise",0,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        java.util.Set<Integer> trees=new java.util.HashSet<Integer>();
        if(args.length==1) {
            String[] ids=list(args[0],"[0-9]{1,3}",64);
            if(ids==null) return invalidArgs("treeId");
            for(String id:ids) trees.add(Integer.parseInt(id));
        }
        int rows=dataTableGetNumRows(EXPERTISE_TABLE);
        java.util.List<Integer> order=new java.util.ArrayList<Integer>();
        for(int row=0;row<rows;row++) order.add(row);
        order.sort((a,b)->{
            int t=Integer.compare(dataTableGetInt(EXPERTISE_TABLE,a,"TIER"),dataTableGetInt(EXPERTISE_TABLE,b,"TIER"));
            return t!=0?t:Integer.compare(dataTableGetInt(EXPERTISE_TABLE,a,"RANK"),dataTableGetInt(EXPERTISE_TABLE,b,"RANK"));
        });
        if(!hasSkill(bot,"expertise")) grantSkill(bot,"expertise");
        int granted=0,already=0,failed=0;
        for(int row:order) {
            String skill=dataTableGetString(EXPERTISE_TABLE,row,"NAME");
            int tree=dataTableGetInt(EXPERTISE_TABLE,row,"TREE");
            if(skill==null || skill.length()==0 || tree==EXPERTISE_TEST_TREE || (!trees.isEmpty() && !trees.contains(tree))) continue;
            if(hasSkill(bot,skill)) already++;
            else if(grantSkill(bot,skill)) granted++;
            else failed++;
        }
        StringBuilder sb=start("ok");
        kv(sb,"granted",granted);kv(sb,"already",already);kv(sb,"failed",failed);
        return sb.toString();
    }

    /**
     * grantSkills <regex>: grants every skill whose name fully matches, in
     * table order (prerequisites before dependents). The regex is at most 64
     * characters from a small allow-list: no backslash escapes (so no
     * back-references), no counted repetition, no quantifier applied to a
     * group (rules out nested-quantifier forms that backtrack exponentially),
     * at most two '*'/'+' and three quantifiers in total (bounds polynomial
     * backtracking). Names longer than 128 characters are skipped.
     */
    public String grantSkills(String value) throws InterruptedException {
        Object[] q=request(value,"grantSkills",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String re=args[0];
        if(re.length()>64 || !re.matches("[A-Za-z0-9_.*+?|()\\[\\]^$-]{1,64}") || re.matches(".*\\)[*+?].*")) return invalidArgs("regex");
        int unbounded=0,quantifiers=0;
        for(int i=0;i<re.length();i++) {
            char ch=re.charAt(i);
            if(ch=='*' || ch=='+') unbounded++;
            if(ch=='*' || ch=='+' || ch=='?') quantifiers++;
        }
        if(unbounded>2 || quantifiers>3) return invalidArgs("regex-quantifiers");
        java.util.regex.Pattern pattern;
        try {pattern=java.util.regex.Pattern.compile(re);}
        catch(RuntimeException e) {return invalidArgs("regex");}
        String[] names=dataTableGetStringColumn(SKILLS_TABLE,"NAME");
        int granted=0,already=0,failed=0;
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        for(String skill:names==null?new String[0]:names) {
            if(skill==null || skill.length()==0 || skill.length()>128 || !pattern.matcher(skill).matches()) continue;
            if(hasSkill(bot,skill)) already++;
            else if(grantSkill(bot,skill)) granted++;
            else {failed++;row(sb,rc,"failed",skill);}
        }
        kv(sb,"granted",granted);kv(sb,"already",already);kv(sb,"failed",failed);
        return end(sb,rc);
    }

    /**
     * grantSchematics: grants every compiled draft schematic template found
     * on the server's data tree. Abstract base schematics are expected to fail.
     */
    public String grantSchematics(String value) throws InterruptedException {
        Object[] q=request(value,"grantSchematics",0,0);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];
        java.io.File root=null;
        for(String dir:DRAFT_SCHEMATIC_DIRS) {
            java.io.File f=new java.io.File(dir);
            if(f.isDirectory()) {root=f;break;}
        }
        if(root==null) return fail("unavailable reason=no-schematic-tree");
        java.util.List<String> templates=new java.util.ArrayList<String>();
        java.util.ArrayDeque<java.io.File> pending=new java.util.ArrayDeque<java.io.File>();
        pending.add(root);
        boolean truncatedTree=false;
        while(!pending.isEmpty() && !truncatedTree) {
            java.io.File[] entries=pending.poll().listFiles();
            for(java.io.File entry:entries==null?new java.io.File[0]:entries) {
                if(templates.size()>=SCHEMATIC_FILE_MAX) {truncatedTree=true;break;}
                if(entry.isDirectory()) pending.add(entry);
                else if(entry.getName().endsWith(".iff")) {
                    String path=entry.getPath().replace('\\','/');
                    int at=path.indexOf("object/draft_schematic/");
                    if(at>=0) {
                        String t=path.substring(at);
                        if(t.matches("object/[a-z0-9_/]+\\.iff")) templates.add(t);
                    }
                }
            }
        }
        int granted=0,already=0,failed=0;
        for(String t:templates) {
            if(hasSchematic(bot,t)) already++;
            else if(grantSchematic(bot,t)) granted++;
            else failed++;
        }
        StringBuilder sb=start("ok");
        kv(sb,"found",templates.size());kv(sb,"granted",granted);kv(sb,"already",already);
        kv(sb,"failed",failed);kv(sb,"tree_truncated",truncatedTree);
        return sb.toString();
    }

    /**
     * itemBonuses <itemOid> <mod=value,...>: replaces the skill-mod bonus
     * objvars on an item the bot carries or wears (worn items apply them on
     * the next equip or login). At most 32 mods, values -10000..10000.
     */
    public String itemBonuses(String value) throws InterruptedException {
        Object[] q=request(value,"itemBonuses",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id item=oid(args[0]);
        String[] pairs=list(args[1],NAME_RE+"=-?[0-9]{1,5}",32);
        if(item==null || pairs==null) return invalidArgs("itemBonuses");
        String s=scope(bot,item,false);
        if(s!=null) return fail(s);
        if(!bot.equals(utils.getContainingPlayer(item))) return fail("out-of-scope reason=not-carried object="+item);
        int[] values=new int[pairs.length];
        for(int i=0;i<pairs.length;i++) {
            Integer v=integer(pairs[i].substring(pairs[i].indexOf('=')+1),-10000,10000);
            if(v==null) return invalidArgs("value");
            values[i]=v;
        }
        removeObjVar(item,"skillmod.bonus");
        StringBuilder applied=new StringBuilder();
        for(int i=0;i<pairs.length;i++) {
            String mod=pairs[i].substring(0,pairs[i].indexOf('='));
            setObjVar(item,"skillmod.bonus."+mod,values[i]);
            applied.append(i==0?"":",").append(enc(mod+"="+values[i]));
        }
        return P+"ok item="+item+" template="+enc(getTemplateName(item))+" bonuses="+applied;
    }

    /**
     * giveStatic <name,...>: creates master_item static items in the bot's
     * inventory (developer.claude.give_static, done directly here). At most
     * 25 names; each must be a row of the master item table.
     */
    public String giveStatic(String value) throws InterruptedException {
        Object[] q=request(value,"giveStatic",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String[] names=list(args[0],NAME_RE,25);
        if(names==null) return invalidArgs("name");
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        int created=0,failed=0;
        StringBuilder sb=start("ok");
        int[] rc=new int[2];
        for(String n:names) {
            obj_id item=null;
            if(dataTableSearchColumnForString(n,"name",static_item.MASTER_ITEM_TABLE)>=0)
                item=static_item.createNewItemFunction(n,inventory);
            if(isIdValid(item)) {created++;row(sb,rc,n,item);}
            else {failed++;row(sb,rc,n,"failed");}
        }
        kv(sb,"created",created);kv(sb,"failed",failed);
        return end(sb,rc);
    }

    /** give <objectOid>: puts an in-scope object into the bot's inventory. */
    public String give(String value) throws InterruptedException {
        Object[] q=request(value,"give",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id x=oid(args[0]);
        if(x==null) return invalidArgs("objectOid");
        String s=movable(bot,x);
        if(s!=null) return fail(s);
        obj_id inventory=utils.getInventoryContainer(bot);
        if(!isIdValid(inventory)) return fail("refused reason=no-inventory");
        boolean ok=putIn(x,inventory);
        StringBuilder sb=start(ok?"ok":"refused");
        kv(sb,"object",x);kv(sb,"inventory",inventory);
        return sb.toString();
    }

    /** completeCollection <bookName>: completes every slot in one player-facing collection book. */
    public String completeCollection(String value) throws InterruptedException {
        Object[] q=request(value,"completeCollection",1,1);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        String book=name(args[0]);
        boolean known=false;
        if(book!=null) for(String b:PLAYER_COLLECTION_BOOKS) if(b.equals(book)) known=true;
        if(!known) return invalidArgs("bookName");
        int rows=dataTableGetNumRows(COLLECTION_TABLE);
        String currentBook="";
        int completed=0,alreadyDone=0,failed=0;
        for(int row=0;row<rows;row++) {
            String bookName=dataTableGetString(COLLECTION_TABLE,row,"bookName");
            if(bookName!=null && bookName.length()>0) {currentBook=bookName;continue;}
            String slot=dataTableGetString(COLLECTION_TABLE,row,"slotName");
            if(slot==null || slot.length()==0 || !currentBook.equals(book)) continue;
            int max=dataTableGetInt(COLLECTION_TABLE,row,"maxSlotValue");
            long current=getCollectionSlotValue(bot,slot);
            long delta=max>0?max-current:(hasCompletedCollectionSlot(bot,slot)?0:1);
            if(delta<=0) alreadyDone++;
            else if(modifyCollectionSlotValue(bot,slot,delta)) completed++;
            else failed++;
        }
        StringBuilder sb=start("ok");
        kv(sb,"book",book);kv(sb,"completed",completed);kv(sb,"already",alreadyDone);kv(sb,"failed",failed);
        return sb.toString();
    }

    /**
     * clearDecor <buildingOid> <tag>: destroys every object directly in the
     * building's cells that a layout tagged with this claude.decor tag ("*"
     * for every tagged object). The bot must own the building. At most 500.
     */
    public String clearDecor(String value) throws InterruptedException {
        Object[] q=request(value,"clearDecor",2,2);
        if(q[0]!=null) return fail((String)q[0]);
        obj_id bot=(obj_id)q[1];String[] args=(String[])q[2];
        obj_id building=oid(args[0]);
        String tag=args[1];
        if(building==null || !(tag.equals("*") || tag.matches("[A-Za-z0-9_:]{1,64}"))) return invalidArgs("clearDecor");
        String s=scope(bot,building,false);
        if(s!=null) return fail(s);
        if(!player_structure.isOwner(building,bot)) return fail("refused reason=not-owner building="+building);
        int removed=0;
        boolean capped=false;
        obj_id[] cells=getContents(building);
        if(cells!=null) for(obj_id cell:cells) {
            obj_id[] inside=isIdValid(cell)?getContents(cell):null;
            if(inside!=null) for(obj_id x:inside) {
                if(!isIdValid(x) || isPlayer(x) || !hasObjVar(x,DECOR_TAG_VAR)) continue;
                if(!tag.equals("*") && !tag.equals(getStringObjVar(x,DECOR_TAG_VAR))) continue;
                if(removed>=CLEAR_DECOR_MAX) {capped=true;break;}
                if(destroyObject(x)) removed++;
            }
            if(capped) break;
        }
        StringBuilder sb=start("ok");
        kv(sb,"building",building);kv(sb,"tag",tag);kv(sb,"removed",removed);kv(sb,"capped",capped);
        return sb.toString();
    }
}
