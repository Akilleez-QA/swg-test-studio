package script.fixture;
import script.*;
import script.library.*;

/** Typed setup of retained fixture actors in original public ground cells.
 * The declared local search is a test input, not an authored entrance claim.
 * These methods neither grant a private lease nor write saved-object records.
 */
public class ground_cell_entry extends protocol_bot {
    private static final String[] SCENES={"kashyyyk_dead_forest","kashyyyk_hunting","kashyyyk_main"};
    private static final long[] ROOTS={-281474976740656L,-28428972650806234L,-56576470324871856L};
    private static final long[] CELLS={-281474976740655L,-28428972650806233L,-56576470324871855L};
    private static final int[] SCENE_ROWS={0,1,2};
    private static final String[] TEMPLATES={"object/building/kashyyyk/ep3_forest_webweaver.iff",
        "object/building/kashyyyk/poi_kash_rodian_hut.iff","object/building/military/military_outpost_guard_house_imperial.iff"};
    private static final float[][] POINTS={{211.77f,9.65877f,326.23f},{284.91f,48f,493.58f},{-665.44f,18.8235f,-108.17f}};
    private int selected() {
        for(int i=0;i<SCENES.length;i++)if(SCENES[i].equals(getCurrentSceneName()))return i;
        return -1;
    }
    private boolean quiet(obj_id p) throws InterruptedException {
        return isIdValid(p) && isPlayerConnected(p) && !isDead(p) && !isIncapacitated(p) && !isIdValid(getGroupObject(p)) &&
            getState(p,STATE_COMBAT)==0 && !hasObjVar(p,"capacity.groupTransfer.id") &&
            !hasObjVar(p,"hasOutstandingRequestSceneTransfer") && getCurrentZoneInstanceId()>0L &&
            getZoneInstanceId(p)==getCurrentZoneInstanceId();
    }
    private boolean publicRoot(int index,obj_id root,obj_id cell) throws InterruptedException {
        if(index<0 || index>=SCENES.length || !originalScene(index) || !isIdValid(root) || !isIdValid(cell) ||
                !root.isAuthoritative() || !cell.isAuthoritative() || !exists(root) || !exists(cell) ||
                !TEMPLATES[index].equals(getTemplateName(root)) || !root.equals(getTopMostContainer(cell)) ||
                getZoneInstanceId(root)!=getCurrentZoneInstanceId() || getZoneInstanceId(cell)!=getCurrentZoneInstanceId())return false;
        for(String key:new String[]{"isControllerObject","instance_name","space_dungeon.name","capacity.encounter"})
            if(hasObjVar(root,key)||hasObjVar(cell,key))return false;
        String room=getCellName(cell);location point=getLocation(root);
        return room!=null && room.length()>0 && cell.equals(getCellId(root,room)) &&
            point!=null && SCENES[index].equals(point.area) && !isIdValid(point.cell) &&
            Math.abs(point.x-POINTS[index][0])<.1f && Math.abs(point.y-POINTS[index][1])<.1f &&
            Math.abs(point.z-POINTS[index][2])<.1f;
    }
    private boolean originalScene(int index) throws InterruptedException {
        String table="datatables/buildout/buildout_scenes.iff";int count=dataTableGetNumRows(table),selected=-1;
        if(index<0 || index>=SCENES.length || count<1 || count>256)return false;
        for(int row=0;row<count;row++)if(SCENES[index].equals(dataTableGetString(table,row,"sceneName"))) {
            if(selected!=-1)return false;selected=row;
        }
        return selected==SCENE_ROWS[index];
    }
    private String queue(String value,boolean entering) throws InterruptedException {
        String method=entering?"enter":"approach";obj_id p=player(identity(value,method));int index=selected();
        if(!quiet(p) || index<0 || !originalScene(index) || !isManagedWorldEntryEnabled(SCENES[index]) ||
                utils.hasScriptVar(p,"fixture.ground.active"))return "protocol_bot=invalid-ground-cell";
        int serial=getIntObjVar(p,"fixture.ground.serial");
        if(serial<0 || serial==Integer.MAX_VALUE)return "protocol_bot=invalid-ground-serial";
        if(entering && !publicRoot(index,obj_id.getObjId(ROOTS[index]),obj_id.getObjId(CELLS[index])))
            return "protocol_bot=invalid-ground-root";
        if(!hasScript(p,"fixture.ground_cell_entry"))attachScript(p,"fixture.ground_cell_entry");
        if(!setObjVar(p,"fixture.ground.serial",serial+1))return "protocol_bot=ground-cell accepted=false";
        dictionary request=new dictionary();request.put("identity",value);request.put("method",method);
        request.put("serial",serial+1);request.put("index",index);request.put("entering",entering);
        request.put("scene",getCurrentSceneName());request.put("world",Long.toString(getCurrentZoneInstanceId()));
        request.put("top",getTopMostContainer(p));
        utils.setScriptVar(p,"fixture.ground.active",serial+1);
        utils.setScriptVar(p,"fixture.ground.result","queued:"+(serial+1));
        boolean accepted=messageTo(p,"fixtureGroundCell",request,.1f,false);
        if(!accepted)utils.removeScriptVar(p,"fixture.ground.active");
        return "protocol_bot=ground-cell accepted="+accepted+" queued="+accepted+" serial="+(serial+1);
    }
    public int fixtureGroundCell(obj_id self,dictionary request) throws InterruptedException {
        if(request==null)return SCRIPT_CONTINUE;
        obj_id p=player(identity(request.getString("identity"),request.getString("method")));
        int serial=request.getInt("serial"),index=request.getInt("index");
        if(!isIdValid(p) || !self.equals(p) || serial<=0 || serial!=getIntObjVar(p,"fixture.ground.serial") ||
                serial!=utils.getIntScriptVar(p,"fixture.ground.active") ||
                !(request.getBoolean("entering")?"enter":"approach").equals(request.getString("method")))return SCRIPT_CONTINUE;
        utils.removeScriptVar(p,"fixture.ground.active");utils.setScriptVar(p,"fixture.ground.result","refused:"+serial);
        if(!quiet(p) || index<0 || index>=SCENES.length || selected()!=index || !isManagedWorldEntryEnabled(SCENES[index]) ||
                !getCurrentSceneName().equals(request.getString("scene")) ||
                !Long.toString(getCurrentZoneInstanceId()).equals(request.getString("world")) ||
                !getTopMostContainer(p).equals(request.getObjId("top")))return SCRIPT_CONTINUE;
        boolean accepted;
        if(request.getBoolean("entering")) {
            obj_id root=obj_id.getObjId(ROOTS[index]),cell=obj_id.getObjId(CELLS[index]);
            if(!publicRoot(index,root,cell))return SCRIPT_CONTINUE;
            location point=null;
            float[] axes={0,2,-2,4,-4},heights={-64,-32,-16,-8,-4,-2,0,2,4,8,16,32,64};
            for(float x:axes)for(float z:axes)for(float y:heights) {
                if(point!=null)break;
                location candidate=new location(x,y,z,SCENES[index],cell);
                if(isValidInteriorLocation(candidate))point=candidate;
            }
            if(point==null)return SCRIPT_CONTINUE;
            vector world=getTransform_o2w(cell).rotateTranslate_l2p(new vector(point.x,point.y,point.z));
            accepted=warpPlayerToInstance(p,SCENES[index],getCurrentZoneInstanceId(),world.x,world.y,world.z,
                    root,getCellName(cell),point.x,point.y,point.z,"",true);
        } else {
            float[] point=POINTS[index];
            accepted=warpPlayerToInstance(p,SCENES[index],getCurrentZoneInstanceId(),point[0],point[1]+2,point[2],
                    null,point[0],point[1]+2,point[2],"",true);
        }
        utils.setScriptVar(p,"fixture.ground.result",(accepted?"issued:":"refused:")+serial);
        return SCRIPT_CONTINUE;
    }
    public String approach(String value) throws InterruptedException {return queue(value,false);}
    public String enter(String value) throws InterruptedException {return queue(value,true);}
    public String inspectCell(String value) throws InterruptedException {
        obj_id p=player(identity(value,"inspectCell"));int index=selected();
        if(!isIdValid(p)||!isPlayerConnected(p)||index<0||getCurrentZoneInstanceId()<=0L)
            return "protocol_bot=invalid-ground-observation";
        obj_id root=obj_id.getObjId(ROOTS[index]),cell=obj_id.getObjId(CELLS[index]);
        boolean rootExists=exists(root),cellExists=exists(cell);location point=rootExists?getLocation(root):null;
        return "protocol_bot=ground-cell-observation ready="+publicRoot(index,root,cell)+
            " root="+root+" cell="+cell+" table_match="+originalScene(index)+
            " root_exists="+rootExists+" cell_exists="+cellExists+
            " root_authoritative="+(rootExists&&root.isAuthoritative())+" cell_authoritative="+(cellExists&&cell.isAuthoritative())+
            " root_world="+(rootExists?getZoneInstanceId(root):-1L)+" cell_world="+(cellExists?getZoneInstanceId(cell):-1L)+
            " template="+(rootExists?getTemplateName(root):"none")+" cell_top="+(cellExists?getTopMostContainer(cell):null)+
            " root_x="+(point==null?Float.NaN:point.x)+" root_y="+(point==null?Float.NaN:point.y)+" root_z="+(point==null?Float.NaN:point.z);
    }
}
