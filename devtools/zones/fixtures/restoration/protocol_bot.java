package script.fixture;
import script.*;
import script.library.*;

/**
 * Lean protocol_bot for the restoration server profile: read-only inspection
 * of one dedicated bot, for login, logout and saved-state checks. The server
 * tree has no zone instances, so those fields report the fixed value "none".
 *
 * Invoked through the CentralServer console:
 *   game <serverId> runScript fixture.protocol_bot inspect <oid>:<stationId>:<characterName>
 *
 * Same guards as the original fixture: answers only on an isolated fixture
 * (GameServer.clientIsolationFixture=1 and a WGC_ copied schema) and only for
 * the exact registered non-god bot on its authoritative game server.
 */
public class protocol_bot extends base_script {
    private static final String NONE="none";

    protected String[] identity(String value, String method) throws InterruptedException {
        if(value==null || value.length()>128) return null;
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
        location w=getWorldLocation(p);
        obj_id g=getGroupObject(p);
        obj_id[] members=isIdValid(g)?getGroupMemberIds(g):null;
        return "protocol_bot=present player="+p+" connected="+isPlayerConnected(p)+
                " scene="+l.area+" instance="+NONE+" cell="+l.cell+
                " building="+getTopMostContainer(p)+" room="+getCellName(l.cell)+
                " x="+l.x+" y="+l.y+" z="+l.z+
                " world_x="+(w==null?Float.NaN:w.x)+" world_y="+(w==null?Float.NaN:w.y)+" world_z="+(w==null?Float.NaN:w.z)+
                " posture="+getPosture(p)+" combat="+getState(p,STATE_COMBAT)+
                " dead="+isDead(p)+" health="+getAttrib(p,HEALTH)+" max_health="+getMaxAttrib(p,HEALTH)+
                " fixture_version=restoration-lean-v1"+
                " fixture_attached="+hasScript(p,"fixture.protocol_bot")+
                " family="+NONE+" instance_controller="+NONE+" ship_instance="+NONE+
                " pending=false protected=false"+
                " outstanding="+hasObjVar(p,"hasOutstandingRequestSceneTransfer")+
                " group="+g+" leader="+(isIdValid(g)?getGroupLeaderId(g):null)+
                " members="+(members==null?0:members.length);
    }
}
