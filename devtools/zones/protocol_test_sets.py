#!/usr/bin/env python3
"""Execute saved, versioned character test sets and retain JSON/JUnit results.

Manifests describe allowlisted driver operations, never shell commands. Each
runtime backend owns the management lock and dedicated-bot/fixture guards.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from prepare_client_fixture_schema import REPO
from studio_tool_bundle import zone_tool_hashes

SETS = Path(__file__).with_name('test_sets')
OPTIONS = {'create': bool, 'disconnect': bool, 'prepare_terminal': bool, 'position_terminal_only': bool, 'stage_station': bool,
           'require_hosted_public_instance': bool,
           'expect_scene': str, 'expect_family': str, 'answer': str,
           'terminal': str, 'prompt': str, 'menu_type': int, 'clone_scene': str}


def source_hashes():
    from protocol_native_gates import GATES
    root = Path(__file__).parent
    studio_sources = ('retained_peer.py','recording_fixture.py','test_retained_peer.py','test_recording_fixture.py',
                      'test_semantics.py','test_semantics.cpp','test_capture.py','test_capture.cpp','test_identity.py')
    names = {'../../src/engine/shared/library/sharedNetwork/src/linux/TcpClient.cpp', '../../src/engine/shared/library/sharedNetwork/src/linux/TcpClient.h', 'ProtocolCompanionRoster.h', 'build_protocol_driver64.py', 'protocol_driver.py', 'protocol_driver64.cpp', 'protocol_scenarios.py',
             'protocol_fault_scenarios.py', 'protocol_preservation.py', 'protocol_native_gates.py', 'world_save_scenario.py', 'world_shutdown_scenario.py', 'reviewed_shutdown.py', 'automatic_retirement_scenario.py', 'retirement_live_fault.py', 'retirement_fault_recovery.py', 'retirement_offline.py', 'retirement_falcon.py', 'retirement_offline_recovery.py', 'fixture_retirement_signal.cpp', 'retirement_inventory.py', 'fixtures/retirement_claim.java', 'prepare_retirement_fixture.py',
             'protocol_fixture_restart.py', 'rryatt_live.py', 'rryatt_fault.py', 'rryatt_demand.py', 'rryatt_demand_content.py', 'rryatt_demand_capacity.py', 'rryatt_demand_combat.py', 'rryatt_demand_fault.py', 'rryatt_fault_tools.py', 'fixture_rryatt_signal.cpp', 'runtime_policy.py', 'rryatt_runtime_policy.py', 'rryatt_group.py', 'test_rryatt_group_actions.py', 'rryatt_recovery.py', 'test_rryatt_recovery_actions.py', 'rryatt_linked.py', 'test_rryatt_linked.py', 'test_protocol_bot_console.py',
             'prepare_protocol_driver.py', 'prepare_stage5_client_fixture64.py',
             'build_protocol_bot_console.py', 'inspect_client_fixture.py',
             'fixture_worker_signal.cpp', 'fixtures/protocol_bot.java', 'test_protocol_driver.py',
             'test_login_recovery.py', 'admission_pressure_probe.py', 'test_login_save_barrier.py', 'stage5_release_evidence.py', 'stage6_release_evidence.py', 'package_instance_release64.py', 'stage_observation64.py', '../docker/check_zones.py', 'instance_readiness.py', 'build_capacity_console.py', 'capacity_console.cpp', 'release_tools.py'}
    names.update('../teststudio_server/'+name for name in studio_sources)
    names.add('studio_actions.py')
    names.update(('hoth_heroic_fixture.py','private_crew_fixture.py','private_group_fixture.py','fixtures/private_ship_crew.java',
                  'fixtures/private_ship_passenger.java','private_ship_round_trip.py','heroic_group_live.py','fixtures/heroic_entry.java',
                  '../../src/engine/server/library/serverGame/src/shared/network/CapacityPlayerWorld.h'))
    for probes in GATES.values():
        for name in probes:
            names.add('test_'+name+'.py')
            if (root/('test_'+name+'.cpp')).exists():
                names.add('test_'+name+'.cpp')
    names.update(p.name for p in root.glob('*_fixture.h'))
    names.update(('../../src/engine/server/application/CentralServer/src/shared/PrivateDepartureJournal.h',
                  '../../src/engine/server/library/serverGame/src/shared/core/Client.cpp', 'instance_journal.cpp'))
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name for name in
                 ('PrivateShipCrewJourney.h','GroupAdmissionEvidence.h'))
    names.update('../../src/engine/server/library/serverUtility/'+part+'/'+name+'.h'
                 for part in ('src/shared','include/public/serverUtility')
                  for name in ('HostedPrivateAccessPolicy','HostedPrivateCrewReference','HostedHeroicGroup'))
    names.update('../../src/engine/server/library/serverNetworkMessages/'+part+'/CapacityPrivateCrew.h'
                 for part in ('src/shared/centralGameServer','include/public/serverNetworkMessages'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/PrivateCrewRequests.h')
    names.update('../../src/engine/server/library/serverGame/src/shared/object/'+name
                 for name in ('GroupIdObserver.cpp','GroupIdObserver.h'))
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name+'.h'
                 for name in ('PendingArrivalRecovery','CompletedLoginLoads','GroupTransferPlacement','RetirementCohortSeats','RetirementCohortAuthority','GroupInstanceRouting','GroupInstanceAdmission','GroupEntryPreparation','InstanceAdmissionCapacity','InstanceAdmissionReservations','HostedPrivateGroupSelection','HostedPrivateClaimAffinity'))
    names.update('../../src/engine/server/library/serverNetworkMessages/src/shared/centralGameServer/'+name+'.h'
                 for name in ('CapacityGroupEntry','CapacityGroupTransfer','CapacityPrivateChoice','EncounterSave','EncounterCensus'))
    names.add('../../src/engine/server/library/serverNetworkMessages/include/public/serverNetworkMessages/CapacityPrivateChoice.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/network/PrivateChoiceRequests.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/core/ServerUIManager.cpp')
    names.update('../../dsrc/sku.0/sys.server/compiled/game/script/'+name for name in (
        'library/space_dungeon.scriptlib','library/utils.scriptlib','item/travel_ticket/travel_space_dungeon.script',
        'item/travel_ticket/travel_player_space_dungeon.script',
        'theme_park/dungeon/trando_slave_camp/kachirho_slave_gate.script',
        'conversation/story_arc_chapter_three_pilot.script','conversation/story_arc_chapter_three_scout.script',
        'player/player_travel.script'))
    names.update('../../src/engine/server/library/serverUtility/'+name for name in (
        'src/shared/HostedPrivateChoiceReference.h','include/public/serverUtility/HostedPrivateChoiceReference.h'))
    names.update('../../src/engine/server/library/serverDatabase/'+name for name in ('src/shared/EncounterCensusPrefix.h','src/shared/EncounterCensusPrefixPersister.cpp','include/public/serverDatabase/EncounterCensusPrefix.h','src/shared/DatabaseProcess.cpp'))
    names.update('../../src/engine/server/library/serverGame/src/shared/network/'+name for name in ('EncounterCensusFrames.h','CentralConnection_Census.cpp','CentralConnection.h'))
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/EncounterCensusPrefix.h','include/public/serverNetworkMessages/EncounterCensusPrefix.h'))
    names.update('../../src/engine/server/library/serverUtility/'+name for name in ('src/shared/EncounterWriterFence.h','include/public/serverUtility/EncounterWriterFence.h'))
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/EncounterWriterSeal.h','include/public/serverNetworkMessages/EncounterWriterSeal.h'))
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/EncounterDiscovery.h','include/public/serverNetworkMessages/EncounterDiscovery.h'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterBootstrap.cpp')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterEnrollment.cpp')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterWithdrawal.cpp')
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/EncounterEnrollment.h','include/public/serverNetworkMessages/EncounterEnrollment.h'))
    names.add('../../src/engine/server/library/serverUtility/src/shared/EncounterCensusState.h')
    names.update('../../src/engine/server/library/serverUtility/'+name for name in ('src/shared/EncounterNativeFloor.h','include/public/serverUtility/EncounterNativeFloor.h'))
    names.update('../../src/engine/server/library/serverGame/'+name for name in ('src/shared/object/EncounterNativeCensus.h','src/shared/object/EncounterNativeCensus.cpp','include/public/serverGame/EncounterNativeCensus.h','src/shared/object/ServerObject_Synchronization.cpp','src/shared/object/ServerObject.cpp','src/shared/network/CentralConnection.cpp'))
    names.add('../../src/engine/server/library/serverUtility/include/public/serverUtility/EncounterCensusState.h')
    names.add('../../src/engine/server/library/serverNetworkMessages/include/public/serverNetworkMessages/EncounterCensus.h')
    names.update('../../src/engine/server/library/serverDatabase/src/shared/'+name for name in ('TaskEncounterCensus.h','TaskEncounterCensus.cpp','EncounterCensusPersister.cpp'))
    names.add('../../src/engine/server/library/serverDatabase/include/public/serverDatabase/TaskEncounterCensus.h')
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name for name in ('CentralServer_EncounterCensus.cpp','ConsoleCommandParser.cpp'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/EncounterCleanupBook.h')
    names.add('../../src/engine/server/application/CentralServer/src/shared/EncounterEpochJournal.h')
    names.update('../../dsrc/sku.0/'+name for name in (
        'sys.server/compiled/game/object/tangible/loot/misc/recording_rod_s01.tpf',
        'sys.server/compiled/game/object/tangible/base/tangible_base.tpf',
        'sys.shared/compiled/game/object/tangible/loot/misc/shared_recording_rod_s01.tpf'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/EncounterLeaseJournal.h')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterSave.cpp')
    names.add('../../src/engine/server/library/serverUtility/src/shared/EncounterCleanupScope.h')
    names.add('../../src/engine/server/library/serverUtility/src/shared/EncounterOwnershipRecord.h')
    names.add('../../src/engine/server/library/serverUtility/include/public/serverUtility/EncounterOwnershipRecord.h')
    names.update('../../src/engine/server/library/serverDatabase/src/shared/'+name for name in ('EncounterOwnershipCensus.h','EncounterOwnershipCensus.cpp'))
    names.add('../../src/engine/server/library/serverDatabase/include/public/serverDatabase/EncounterOwnershipCensus.h')
    names.update('../../src/engine/server/library/serverGame/src/shared/object/'+name for name in ('EncounterOwnershipVariables.h','ServerObject_ObjVar.cpp','ServerObject.h'))
    names.update('../../src/engine/server/library/serverUtility/src/shared/'+name for name in ('EncounterObjectOrigins.h','EncounterObjectOrigins.cpp'))
    names.add('../../src/engine/server/library/serverUtility/include/public/serverUtility/EncounterObjectOrigins.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/core/ServerWorld.cpp')
    names.add('hosted_login_contract.py')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/universe/planets.mif')
    from hosted_login_contract import model as hosted_login_model
    names.update('../../'+name for name in hosted_login_model()['input_sha256'])
    names.update('../../src/engine/server/library/serverUtility/'+name for name in (
        'src/shared/HostedLoginContract.h','include/public/serverUtility/HostedLoginContract.h'))
    names.add('../../src/engine/server/library/serverGame/src/shared/object/CreatureObject.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/core/HostedPublicLoginPlacement.h')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/library/capacity_login.scriptlib')
    names.update(('test_ground_authored_cell.py','test_ground_cell_recovery.py','test_mount_logout.py',
                  'test_ord_login_recovery.py','test_falcon_login_recovery.py'))
    names.update('../../src/engine/server/library/serverGame/src/shared/core/'+name
                 for name in ('ServerBuildoutManager.cpp','ServerBuildoutManager.h'))
    names.add('../../src/engine/server/library/serverScript/src/shared/JavaLibrary.cpp')
    names.update('../../src/engine/server/library/serverScript/src/shared/'+name
                 for name in ('ScriptParameters.cpp','ScriptParameters.h'))
    names.add('../../src/game/server/application/SwgGameServer/src/shared/core/SwgGameServer.cpp')
    names.add('../../src/engine/server/library/serverUtility/include/public/serverUtility/EncounterCleanupScope.h')
    names.add('../../src/engine/server/library/serverNetworkMessages/include/public/serverNetworkMessages/EncounterSave.h')
    names.update('../../src/engine/server/library/serverDatabase/src/shared/'+name for name in (
        'EncounterSaveBook.h','EncounterSavePersister.cpp','EncounterDiscoveryPersister.cpp','TaskEncounterDiscovery.h','TaskEncounterDiscovery.cpp','EncounterLoadGraph.h','EncounterLoadGraph.cpp','EncounterReleaseProof.h','TaskEncounterRelease.h','TaskEncounterRelease.cpp','Persister.h','Persister.cpp','WorldSavePersister.cpp'))
    names.update('../../src/engine/server/library/serverDatabase/include/public/serverDatabase/'+name for name in ('EncounterReleaseProof.h','TaskEncounterRelease.h','TaskEncounterDiscovery.h','EncounterLoadGraph.h'))
    names.add('../../src/engine/server/library/serverDatabase/include/public/serverDatabase/EncounterSaveBook.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/network/EncounterSaveFrames.h')
    names.update('../../src/engine/server/library/serverGame/src/shared/network/'+name for name in ('EncounterDiscoveryFrames.h','CentralConnection_EncounterDiscovery.cpp'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterDiscovery.cpp')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_EncounterLoad.cpp')
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/EncounterLoad.h','include/public/serverNetworkMessages/EncounterLoad.h'))
    names.update('../../src/engine/server/library/serverDatabase/src/shared/'+name for name in ('EncounterLoader.cpp','EncounterObjectLocator.cpp','EncounterObjectLocator.h','ObjectLocator.h','Loader.cpp','Loader.h','LoaderSnapshotGroup.cpp','LoaderSnapshotGroup.h'))
    names.add('../../src/engine/server/library/serverDatabase/include/public/serverDatabase/EncounterObjectLocator.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/core/GameServer_EncounterLoad.cpp')
    names.add('../../src/game/server/application/SwgDatabaseServer/src/shared/core/SwgSnapshot.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/network/GroupTravelRequests.h')
    names.update(('instance_scope.py','family_scope.json','../../src/engine/server/library/serverUtility/src/shared/ZoneInstanceScope.h'))
    names.update(('world_runtime_policy.py','world_family_fixture.py','instance_maintenance.py','source_headers.py','fixture_journal_maintenance.py'))
    names.update(('whole_world_live.py','save_world_family_suites.py','fixtures/world_entry.java'))
    names.update(('ground_cell_fixture.py','ground_cell_live.py','ground_group_live.py','fixtures/ground_cell_entry.java'))
    names.add('kachirho_single_live.py')
    names.update(('protocol_clone.py','test_protocol_clone.py'))
    names.add('../../src/engine/shared/library/sharedGame/src/shared/core/SharedBuildoutAreaManager.cpp')
    from ground_cell_fixture import verify_source as ground_targets
    names.update('../../'+name for name in ground_targets()['input_sha256'])
    names.update(('../../src/engine/server/library/serverNetworkMessages/src/shared/centralGameServer/WorldSave.h',
                  '../../src/engine/server/application/TaskManager/src/shared/WorldLaunchFence.h',
                  '../../src/engine/server/application/CentralServer/src/shared/ZoneInstanceRetirement.h',
                  '../../dsrc/sku.0/sys.server/compiled/game/script/base_class.java'))
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name for name in ('LoginAttemptRoutes.h','LoginFamilyDispatch.h','GroupAdmissionPlacement.h','ZoneInstanceRetirementContent.h'))
    names.update(('../../src/engine/server/library/serverNetworkMessages/src/shared/centralGameServer/LoginLoadTypes.h','../../src/engine/server/library/serverGame/src/shared/core/GameServer.cpp','../../src/engine/server/library/serverScript/src/shared/ScriptMethodsObjectMove.cpp','../../dsrc/sku.0/sys.server/compiled/game/script/library/space_transition.scriptlib'))
    names.update(('capacity.py','instance_definitions.py','hosted_content.py','catalog.json','linked_instances.py','audit_references.py','audit_client_areas.py'))
    names.update('../../dsrc/sku.0/sys.server/compiled/game/'+name for name in ('script/library/instance.scriptlib','script/library/township.scriptlib','script/library/space_skill.scriptlib','script/player/base/base_player.script','script/player/player_instance.script','script/player/player_instance.java','script/systems/instance/instance_manager.script','datatables/instance/instance_datatable.tab'))
    names.add('template_controller_evidence.py')
    names.add('hosted_private_entry_contract.py')
    names.add('hosted_private_instances_fixture.py')
    names.add('capacity_wire_contract.py')
    names.update(('test_hosted_private_original_dispatch.py','test_hosted_private_original_access.py'))
    names.update('../../src/engine/server/library/serverGame/src/shared/network/'+name for name in ('CentralConnection_PrivateArrival.cpp','PrivateArrivalPublications.h'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/CentralConnection_PrivateResume.cpp')
    names.add('../../src/engine/server/library/serverScript/src/shared/ScriptMethodsTriggerVolume.cpp')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_PrivateResume.cpp')
    names.add('../../src/engine/server/application/CentralServer/src/shared/HostedPrivateRecoverySource.h')
    names.add('../../src/engine/server/application/CentralServer/src/shared/CompletedLoginLoads.h')
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/CapacityPrivateResume.h','include/public/serverNetworkMessages/CapacityPrivateResume.h'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/LoginFamilyDispatch.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/HostedPrivateArrivalVariables.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/HostedPrivateContinuation.h')
    names.update('../../src/engine/server/library/serverUtility/'+name for name in ('src/shared/HostedPrivateContinuation.h','include/public/serverUtility/HostedPrivateContinuation.h'))
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/CapacityPrivateDeparture.h','include/public/serverNetworkMessages/CapacityPrivateDeparture.h','src/shared/centralGameServer/WorldSave.h'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_WorldSave.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/NativePersistenceVariables.h')
    names.update('../../src/engine/server/library/serverGame/src/shared/core/'+name for name in ('Client.cpp','Client.h','ObserveTracker.cpp','ObserveTracker.h'))
    names.add('../../src/engine/server/application/CentralServer/src/shared/CentralServer_PrivateArrival.cpp')
    names.update('../../src/engine/server/library/serverNetworkMessages/'+name for name in ('src/shared/centralGameServer/CapacityPrivateArrival.h','include/public/serverNetworkMessages/CapacityPrivateArrival.h'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/CentralConnection.h')
    names.add('../../src/engine/server/application/CentralServer/src/shared/HostedPrivateEntryEvidence.h')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/library/space_dungeon_data.scriptlib')
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name for name in ('ContentCapacityObservation.h','CapacityContentRegistration.h','CentralServer_Instances.cpp','ZoneInstanceLifecycle.h'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/CapacityContentSampler.h')
    names.update(('private_solo_admission.py','private_owned_lifecycle.py','hosted_private_mtp_live.py','private_active_join_live.py','test_encounter_automatic_actions.py'))
    names.add('../../src/engine/server/library/serverDatabase/src/shared/DatabaseProcess.cpp')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/theme_park/dungeon/mustafar_trials/establish_the_link/link_event_manager.script')
    names.update('../../dsrc/sku.0/sys.server/compiled/game/script/systems/dungeon_sequencer/sequence_controller'+suffix for suffix in ('.script','.java'))
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/theme_park/dungeon/mustafar_trials/valley_battleground/valley_event_manager.script')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/theme_park/dungeon/mustafar_trials/working_droid_factory/working_controller.script')
    names.add('../../dsrc/sku.0/sys.server/compiled/game/script/theme_park/dungeon/mustafar_trials/working_droid_factory/doom_target.script')
    names.add('private_lease_observation.py')
    names.add('hosted_family_live.py')
    names.add('hosted_capacity_layout.py')
    names.update(('hosted_capacity_returns.py','../../src/engine/server/application/CentralServer/src/shared/HostedContentReadiness.h','../../src/engine/server/library/serverUtility/src/shared/HostedContentReturns.h'))
    names.update(('../../src/engine/server/library/serverUtility/src/shared/HostedContentContract.h','../../src/engine/server/application/CentralServer/src/shared/HostedContentLayout.h'))
    names.update(('../../src/engine/server/library/serverGame/src/shared/network/ZoneInstanceRequests.h','../../src/engine/server/library/serverNetworkMessages/src/shared/centralGameServer/CapacityScene.h','../../src/engine/server/library/serverScript/src/shared/ScriptMethodsWorldInfo.cpp','../../dsrc/sku.0/sys.server/compiled/game/script/base_class.java'))
    names.update(('encounter_withdrawal_live.py','test_encounter_withdrawal_actions.py','encounter_enrollment_live.py','test_encounter_enrollment_actions.py','encounter_offline_live.py','test_encounter_offline_actions.py','test_encounter_release_fixture.py','encounter_load_live.py','test_encounter_load_actions.py','encounter_reuse_live.py','test_encounter_reuse_actions.py','encounter_recovery_live.py','test_encounter_recovery_actions.py','encounter_root_claim_live.py','encounter_bootstrap_live.py','encounter_census_live.py','test_encounter_census_actions.py','encounter_origin_live.py','test_encounter_origin_actions.py','hosted_public_live.py','hosted_public_reconnect.py','hosted_public_contract.py','hosted_snapshot_contract.py','world_growth_evidence.py','test_world_growth_evidence.py',
        'hosted_public_fixture.py','hosted_public_selection.py','hosted_public_instances_fixture.py','hosted_public_login.py','source_input_verification.py','fixtures/hosted_public_entry.java'))
    names.update('../../dsrc/sku.0/sys.server/compiled/game/script/'+name for name in (
        'library/capacity_registration.scriptlib','library/capacity_dungeon_cleanup.scriptlib',
        'theme_park/dungeon/space_dungeon_controller.script','library/space_dungeon.scriptlib',
        'theme_park/dungeon/nova_orion_station/nova_orion_public_instance.script','systems/movement/public_instance_setup.script',
        'theme_park/kashyyyk/hracca_controller.script','theme_park/kashyyyk/hracca_spawner.script',
        'theme_park/kashyyyk/bocctyyy_bet_controller.script','theme_park/kashyyyk/bocctyyy_bet_spawner.script',
        'theme_park/dungeon/avatar_platform/avatar_clean_up.script',
        'theme_park/dungeon/mustafar_trials/obiwan_finale/lair_clean_up.script'))
    names.update('../../src/engine/server/library/serverUtility/src/shared/'+name for name in (
        'HostedPublicCapacityPolicy.h','HostedPublicConfiguration.h','HostedPublicContract.h','HostedSnapshotContract.h'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/HostedSnapshotSampler.h')
    names.add('retirement_central_loss.py')
    names.add('retirement_fault_boundary.py')
    names.update(('central_loss_recovery.py','test_central_loss_recovery.py','retirement_fault_targets.py','fixture_central_signal.cpp','fixture_service_signal.cpp'))
    names.add('retirement_occupied.py')
    names.add('retirement_interrupted_arrival.py')
    names.update(('build_instance_journal.py','instance_journal.cpp'))
    names.add('group_affinity_lifecycle.py')
    names.add('test_retirement_interrupted_arrival.py')
    names.add('test_retirement_fault_baseline.py')
    names.add('retirement_combat_windows.py')
    names.add('../../src/engine/server/application/CentralServer/src/shared/PlanetServerConnection.cpp')
    names.update('../../src/engine/server/application/CentralServer/src/shared/'+name
                 for name in ('CentralServer.cpp','CentralServer.h','CentralServer_WorldShutdown.cpp'))
    names.add('../../src/engine/server/library/serverGame/src/shared/network/CentralConnection.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/network/CentralConnection.h')
    names.update('../../src/engine/server/library/serverGame/src/shared/core/'+name for name in ('Client.cpp','Client.h'))
    names.update('../../src/engine/server/application/ConnectionServer/src/shared/'+name for name in ('GameConnection.cpp','GameConnection.h','Client.cpp','Client.h'))
    names.add('../../src/engine/server/library/serverNetworkMessages/src/shared/gameConnectionServer/ClientHandoff.h')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/ServerObject.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/ShipObject.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/CreatureObject.cpp')
    names.add('../../src/engine/server/library/serverGame/src/shared/object/WeaponObject.cpp')
    names.add('../../src/engine/shared/library/sharedObject/src/shared/object/Object.cpp')
    names.add('../../src/game/server/application/SwgGameServer/src/linux/main.cpp')
    # The generated native root contract depends on area origins as well as
    # portal rows/templates. Pin those actual inputs, not only its generator.
    from hosted_snapshot_contract import model as snapshot_model
    names.update('../../'+name for name in snapshot_model()['input_sha256'])
    # Keep the original native/asset receipts alongside the pinned tools.
    source = {name: hashlib.sha256((REPO/name[6:]).read_bytes()).hexdigest() for name in sorted(names)
              if name.startswith(('../../src/', '../../dsrc/'))}
    source.update(zone_tool_hashes())
    return source


def runtime_artifact(log, folder):
    matches = re.findall(r'^Evidence: (.+)$', log.read_text(), re.M)
    if len(matches) != 1:
        raise ValueError('Runtime case must retain exactly one structured result')
    result = (Path(matches[0])/'result.json').resolve(strict=True)
    if not result.is_relative_to(folder.resolve()/'protocol-driver'):
        raise ValueError('Runtime evidence is outside the dedicated fixture')
    data = json.loads(result.read_text())
    if data.get('passed') is not True or data.get('fully_unloaded') is not True:
        raise ValueError('Runtime backend did not prove a pass and full unload')
    return {'path': str(result), 'sha256': hashlib.sha256(result.read_bytes()).hexdigest()}


def validate(data):
    if set(data) != {'schema_version', 'id', 'title', 'category', 'roles', 'tests'}:
        raise ValueError('Unknown or missing test-set fields')
    if type(data['schema_version']) is not int or data['schema_version'] != 1 or not re.fullmatch('[a-z][a-z0-9_]{2,63}', data['id']):
        raise ValueError('Unsupported test-set schema/identity')
    if data['category'] not in ('unit', 'functional', 'system', 'regression'):
        raise ValueError('Unknown test category')
    if not isinstance(data['title'], str) or not 1 <= len(data['title']) <= 200:
        raise ValueError('Test title required')
    roles = data['roles']
    if (not isinstance(roles, list) or len(roles) > 5 or len(set(roles)) != len(roles) or
            any(not re.fullmatch('[a-z]{3,16}', r) for r in roles)):
        raise ValueError('At most five distinct named bot roles required')
    if not isinstance(data['tests'], list) or not 1 <= len(data['tests']) <= 32:
        raise ValueError('Bounded nonempty test set required')
    ids = set()
    for case in data['tests']:
        if set(case) != {'id', 'kind', 'options'} or not re.fullmatch('[a-z][a-z0-9_]{2,63}', case['id']) or case['id'] in ids:
            raise ValueError('Unique typed test identities required')
        ids.add(case['id'])
        options = case['options']
        if not isinstance(options, dict):
            raise ValueError('Typed options required')
        if case['kind'] == 'protocol_session':
            if options.get('role') not in roles or set(options) - (set(OPTIONS) | {'role'}):
                raise ValueError('Unknown session role or option')
            for key, value in options.items():
                if key != 'role' and type(value) is not OPTIONS[key]:
                    raise ValueError('Incorrect session option type: ' + key)
            if options.get('terminal') and not options.get('prompt'):
                raise ValueError('Explicit radial target requires exact SUI prompt')
            if options.get('create') and any(options.get(k) for k in ('terminal', 'prepare_terminal', 'position_terminal_only', 'stage_station')):
                raise ValueError('Creation must be a separate saved lifecycle')
            if options.get('position_terminal_only') and any(options.get(k) for k in ('terminal','prepare_terminal','stage_station','clone_scene')):
                raise ValueError('Terminal positioning is a separate setup lifecycle')
            if options.get('clone_scene') and (options['clone_scene']!='kashyyyk_main' or any(options.get(k) for k in ('create','stage_station','terminal','prepare_terminal','disconnect'))):
                raise ValueError('Clone recovery requires its separate original-menu and normal-logout lifecycle')
        elif case['kind']=='heroic_group_ejection':
            from heroic_group_live import FAMILIES
            if (set(options)!={'leader','member','remaining','outsider','family'} or options['family'] not in FAMILIES or
                len({options[r] for r in ('leader','member','remaining','outsider')})!=4 or
                {options[r] for r in ('leader','member','remaining','outsider')}!=set(roles)):
                raise ValueError('Four distinct retained heroic roles and one reviewed family required')
        elif case['kind']=='hoth_group_ejection':
            names=('leader','member','remaining','remaining_two','outsider')
            if (set(options)!=set(names)|{'team'} or type(options['team']) is not int or options['team'] not in (1,2) or
                    len({options[r] for r in names})!=5 or {options[r] for r in names}!=set(roles)):
                raise ValueError('Five distinct retained Hoth roles and an original team required')
        elif case['kind']=='ground_cell_group':
            from ground_cell_fixture import SCENES
            if (set(options)!={'leader','member','offline','filler','definition'} or options['definition'] not in SCENES or
                    len({options[r] for r in ('leader','member','offline','filler')})!=4 or
                    {options[r] for r in ('leader','member','offline','filler')}!=set(roles)):
                raise ValueError('Four distinct retained roles and original public ground scene required')
        elif case['kind']=='ground_cell_recovery':
            from ground_cell_fixture import SCENES
            if (set(options)!={'leader','member','offline','definition'} or options['definition'] not in SCENES or
                    len({options['leader'],options['member'],options['offline']})!=3 or
                    {options['leader'],options['member'],options['offline']}!=set(roles)):
                raise ValueError('Three distinct retained roles and original public ground scene required')
        elif case['kind']=='retirement_offline_recovery':
            if (set(options)!={'leader','member','offline','family'} or options['family'] not in ('rryatt','ord','falcon') or
                    len({options['leader'],options['member'],options['offline']})!=3 or
                    {options['leader'],options['member'],options['offline']}!=set(roles)):
                raise ValueError('Two outside witnesses and one distinct offline actor in a reviewed family required')
        elif case['kind'] in ('retirement_fault_recovery','retirement_central_fencing','retirement_central_authorizing','retirement_central_freezing','retirement_central_committing','retirement_central_stopping_games','retirement_central_stopping_planet','retirement_database_authorizing','retirement_coordinator_fencing','retirement_game_supervisor_stopping_games','retirement_planet_supervisor_stopping_planet'):
            if set(options)!={'leader','member','family'} or options['family'] not in ('falcon','ord','rryatt') or options['leader']==options['member'] or not {options['leader'],options['member']}<=set(roles):
                raise ValueError('Exact reviewed family and two distinct roles required')
        elif case['kind'] in ('kachirho_single', 'hosted_capacity', 'private_solo_admission', 'private_owned_lifecycle','hosted_private_mtp','hosted_private_mtp_join', 'private_ship_round_trip', 'encounter_origins', 'encounter_census', 'encounter_automatic', 'encounter_bootstrap', 'encounter_recovery', 'encounter_reuse', 'encounter_load', 'encounter_offline','encounter_enrollment','encounter_withdrawal', 'encounter_root_claim', 'ship_group', 'split_friend', 'combat_windows', 'pending_faults', 'rryatt_entry', 'rryatt_linked', 'rryatt_recovery', 'rryatt_group', 'rryatt_clone', 'rryatt_live_faults','rryatt_demand','rryatt_demand_content','rryatt_demand_combat','rryatt_demand_faults','rryatt_fixture_restart','world_save','distributed_shutdown','reviewed_shutdown','automatic_retirement_rryatt','automatic_retirement_ord'):
            pair=options.get('pair')
            mode=options.get('mode')
            if 'mode' in options and (case['kind']!='rryatt_group' or mode not in ('full','affinity','combat','leases')):
                raise ValueError('Unknown public linked-set scenario mode')
            role_options={k:v for k,v in options.items() if k not in ('pair','mode')}
            if (set(role_options) != {'leader','member'} or len(set(role_options.values())) != 2 or
                    not set(role_options.values()) <= set(roles) or
                    ('pair' in options and (case['kind'] not in ('rryatt_linked','rryatt_recovery','rryatt_group') or type(pair) is not int or pair not in range(3)))):
                raise ValueError('Ship/group suite requires two distinct roles')
        elif case['kind'] in ('capacity_race', 'rryatt_demand_capacity', 'fixture_restart'):
            if options != {'actors': roles} or len(roles) != 5:
                raise ValueError('Capacity race requires exactly five declared actors')
        elif case['kind'] in ('space_split','rryatt_live_capacity','retirement_occupied_rryatt','retirement_occupied_ord','retirement_occupied_outside_rryatt','retirement_occupied_outside_ord','retirement_occupied_combat_rryatt','retirement_occupied_combat_ord', 'retirement_occupied_interrupted_rryatt', 'retirement_occupied_interrupted_ord', 'group_affinity_rryatt', 'group_affinity_ord'):
            if (set(options) != {'leader', 'member', 'filler'} or len(set(options.values())) != 3 or
                    not set(options.values()) <= set(roles)):
                raise ValueError('Separate-space suite requires three distinct roles')
        elif case['kind'] in ('hosted_public_family','hosted_public_instance_family'):
            if (set(options)!={'leader','member','family'} or options['family'] not in ('myyydril_caverns','nova_orion_station') or
                any(not isinstance(options[r],str) for r in ('leader','member')) or
                options['leader']==options['member'] or not {options['leader'],options['member']}<=set(roles)):
                raise ValueError('Public family scenario requires a reviewed public family and two distinct roles')
        elif case['kind'] == 'whole_world_family':
            from world_runtime_policy import eligible
            if (set(options)!={'leader','member','definition'} or
                    not isinstance(options['definition'],str) or options['definition'] not in eligible() or
                    any(not isinstance(options[r],str) for r in ('leader','member')) or
                    options['leader']==options['member'] or not {options['leader'],options['member']}<=set(roles)):
                raise ValueError('Whole-world scenario requires one canonical eligible definition and two distinct roles')
        elif case['kind'] == 'driver_unit':
            if options:
                raise ValueError('Unit cases require no runtime options')
        elif case['kind'] == 'native_gate':
            from protocol_native_gates import GATES
            if set(options) != {'gate'} or options['gate'] not in GATES:
                raise ValueError('Explicit allowlisted native gate required')
        else:
            raise ValueError('Unknown test backend')
    return data


def command(case, bindings, folder, binary, native=None, console=None, retirement_console=None):
    tools = Path(__file__).parent
    options = case['options']
    if case['kind'] == 'driver_unit':
        return [sys.executable, str(tools / 'test_protocol_driver.py')]
    if case['kind'] == 'native_gate':
        if not native or any(value is None for value in native.values()):
            raise ValueError('Native gates require matching overlay, source, STLport and UDP inputs')
        return [sys.executable, str(tools/'protocol_native_gates.py'), '--gate', options['gate'],
                *[item for key, value in native.items() for item in ('--'+key, str(value))]]
    if folder is None or binary is None:
        raise ValueError('Runtime suites require --folder and --binary')
    common = ['--folder', str(folder), '--binary', str(binary)]
    if case['kind'] in ('ground_cell_recovery','ground_cell_group'):
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario',case['kind'],
                '--world-family',options['definition'],'--bots',*[bindings[options[r]] for r in
                    (('leader','member','offline','filler') if case['kind']=='ground_cell_group' else ('leader','member','offline'))]]
    if case['kind'] in ('encounter_origins','encounter_census','encounter_automatic','encounter_bootstrap','encounter_recovery','encounter_reuse','encounter_load','encounter_offline','encounter_enrollment','encounter_withdrawal','encounter_root_claim'):
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario',case['kind'],
                '--bots',bindings[options['leader']],bindings[options['member']]]
    if case['kind'] in ('hosted_public_family','hosted_public_instance_family'):
        scenario=('hosted_public_instance_' if case['kind']=='hosted_public_instance_family' else 'hosted_public_')+('myyydril' if options['family']=='myyydril_caverns' else 'nova')
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario',scenario,
                '--bots',bindings[options['leader']],bindings[options['member']]]
    if case['kind']=='whole_world_family':
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario','whole_world_family',
                '--world-family',options['definition'],'--bots',bindings[options['leader']],bindings[options['member']]]
    if case['kind']=='retirement_offline_recovery':
        if not native or not native.get('overlay') or not native.get('jdk') or console is None or retirement_console is None:
            raise ValueError('Offline recovery requires matching overlay, JDK and both consoles')
        return [sys.executable,str(tools/'retirement_offline_recovery.py'),*common,'--overlay',str(native['overlay']),'--jdk',str(native['jdk']),'--console',str(console),'--retirement-console',str(retirement_console),'--family',options['family'],'--bots',*[bindings[options[r]] for r in ('leader','member','offline')]]
    if case['kind'] in ('retirement_fault_recovery','retirement_central_fencing','retirement_central_authorizing','retirement_central_freezing','retirement_central_committing','retirement_central_stopping_games','retirement_central_stopping_planet','retirement_database_authorizing','retirement_coordinator_fencing','retirement_game_supervisor_stopping_games','retirement_planet_supervisor_stopping_planet'):
        if not native or not native.get('overlay') or not native.get('jdk') or console is None or retirement_console is None:
            raise ValueError('Retirement recovery requires the matching overlay, JDK and both fixture consoles')
        central=case['kind']!='retirement_fault_recovery'
        backend='retirement_central_loss.py' if central else 'retirement_fault_recovery.py'
        phase=(['--boundary','authorizing','--fault-service','database'] if case['kind']=='retirement_database_authorizing'
               else ['--boundary','fencing','--fault-service','coordinator'] if case['kind']=='retirement_coordinator_fencing'
               else ['--boundary','stopping_games','--fault-service','game-supervisor'] if case['kind']=='retirement_game_supervisor_stopping_games'
               else ['--boundary','stopping_planet','--fault-service','planet-supervisor'] if case['kind']=='retirement_planet_supervisor_stopping_planet'
               else ['--boundary',case['kind'][len('retirement_central_'):]] if central else [])
        return [sys.executable,str(tools/backend),*common,'--overlay',str(native['overlay']),'--jdk',str(native['jdk']),'--console',str(console),'--retirement-console',str(retirement_console),'--family',options['family'],'--bots',bindings[options['leader']],bindings[options['member']],*phase]
    if case['kind']=='rryatt_fixture_restart':
        if not native or not native.get('overlay') or not native.get('jdk') or console is None:
            raise ValueError('Rryatt restart requires matching overlay, JDK and console')
        return [sys.executable,str(tools/'protocol_fixture_restart.py'),'--folder',str(folder),'--overlay',str(native['overlay']),'--jdk',str(native['jdk']),'--console',str(console),'--rryatt','--bots',bindings[options['leader']],bindings[options['member']]]
    if case['kind'] == 'fixture_restart':
        if not native or not native.get('overlay') or not native.get('jdk') or console is None:
            raise ValueError('Fixture restart requires the accepted overlay, JDK and matching bot console')
        return [sys.executable, str(tools/'protocol_fixture_restart.py'), '--folder', str(folder),
                '--overlay', str(native['overlay']), '--jdk', str(native['jdk']), '--console', str(console),
                '--bots', *[bindings[role] for role in options['actors']]]
    if case['kind']=='heroic_group_ejection':
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario','heroic_group_ejection',
                '--heroic-family',options['family'],'--bots',*[bindings[options[r]] for r in ('leader','member','remaining','outsider')]]
    if case['kind']=='hoth_group_ejection':
        return [sys.executable,str(tools/'protocol_scenarios.py'),*common,'--scenario','heroic_group_ejection',
                '--heroic-family','echo_base_team'+str(options['team']),'--bots',
                *[bindings[options[r]] for r in ('leader','member','remaining','remaining_two','outsider')]]
    if case['kind'] in ('capacity_race','rryatt_demand_capacity'):
        return [sys.executable, str(tools/'protocol_scenarios.py'), *common, '--scenario', case['kind'],
                '--bots', *[bindings[role] for role in options['actors']]]
    if case['kind'] in ('space_split','rryatt_live_capacity','retirement_occupied_rryatt','retirement_occupied_ord','retirement_occupied_outside_rryatt','retirement_occupied_outside_ord','retirement_occupied_combat_rryatt','retirement_occupied_combat_ord', 'retirement_occupied_interrupted_rryatt', 'retirement_occupied_interrupted_ord', 'group_affinity_rryatt', 'group_affinity_ord'):
        return [sys.executable, str(tools/'protocol_scenarios.py'), *common, '--scenario', case['kind'], '--bots',
                *[bindings[options[role]] for role in ('leader', 'member', 'filler')]]
    if case['kind'] in ('kachirho_single', 'hosted_capacity', 'private_solo_admission', 'private_owned_lifecycle','hosted_private_mtp','hosted_private_mtp_join', 'private_ship_round_trip', 'ship_group', 'split_friend', 'combat_windows', 'pending_faults', 'rryatt_entry', 'rryatt_linked', 'rryatt_recovery', 'rryatt_group', 'rryatt_clone', 'rryatt_live_faults','rryatt_demand','rryatt_demand_content','rryatt_demand_combat','rryatt_demand_faults','rryatt_fixture_restart','world_save','distributed_shutdown','reviewed_shutdown','automatic_retirement_rryatt','automatic_retirement_ord'):
        return [sys.executable, str(tools / 'protocol_scenarios.py'), *common, '--bots',
                bindings[options['leader']], bindings[options['member']], '--scenario', case['kind']] + (['--rryatt-pair',str(options['pair'])] if 'pair' in options else []) + (['--rryatt-group-mode',options['mode']] if 'mode' in options else [])
    result = [sys.executable, str(tools / 'protocol_driver.py'), *common, '--bot', bindings[options['role']]]
    for key, value in options.items():
        if key == 'role' or value is False:
            continue
        result.append('--' + key.replace('_', '-'))
        if value is not True:
            result.append(str(value))
    return result


def execute(argv, log, timeout=1200, env=None):
    """Interrupt a timed-out backend so its guarded cleanup can finish."""
    process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        return process.wait(timeout=timeout), False
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as interrupted:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        if isinstance(interrupted, KeyboardInterrupt):
            raise
        return process.returncode, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--suite', action='append', help='one saved JSON basename in devtools/zones/test_sets; run each suite separately')
    parser.add_argument('--folder', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--bot', action='append', default=[], metavar='ROLE=REGISTRY')
    parser.add_argument('--output', type=Path, help='fresh evidence directory; defaults to private fixture test-sets')
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--native-source-root', type=Path)
    parser.add_argument('--stlport-root', type=Path)
    parser.add_argument('--native-static', type=Path)
    parser.add_argument('--jdk', type=Path)
    parser.add_argument('--bot-console', type=Path)
    parser.add_argument('--retirement-console',type=Path)
    args = parser.parse_args()
    if args.suite and len(args.suite) != 1:
        parser.error('Specify --suite exactly once; run each requested suite separately')
    args.suite = args.suite[0] if args.suite else None
    if args.list:
        for path in sorted(SETS.glob('*.json')):
            data = validate(json.loads(path.read_text()))
            print(f"{data['id']} ({data['category']}): {data['title']} [{len(data['tests'])} tests]")
        return
    if not args.suite or not re.fullmatch('[a-z][a-z0-9_]{2,63}', args.suite):
        parser.error('Select a saved --suite; use --list to inspect suites')
    source = SETS / (args.suite + '.json')
    data = validate(json.loads(source.read_text()))
    bindings = {}
    for value in args.bot:
        pair = value.split('=')
        if len(pair) != 2 or any(not re.fullmatch('[a-z]{3,16}', v) for v in pair) or pair[0] in bindings:
            parser.error('Unique ROLE=REGISTRY bot bindings required')
        bindings[pair[0]] = pair[1]
    if set(bindings) != set(data['roles']) or len(set(bindings.values())) != len(bindings):
        parser.error('Bind every declared role to a distinct retained bot')
    operation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(3)
    if args.output:
        output = args.output
    elif args.folder:
        output = args.folder.resolve() / 'test-sets' / operation
    else:
        output = REPO / 'StarWarsGalaxies/logs/protocol-test-sets' / operation
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'suite.json').write_text(json.dumps(data, indent=2) + '\n')
    report = {'schema_version': 1, 'suite': data['id'], 'operation': operation,
              'category': data['category'], 'manifest_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'source_hashes': source_hashes(),
              'bindings': bindings, 'cases': [], 'passed': False}
    try:
        for case in data['tests']:
            start = time.monotonic()
            native = {key: getattr(args, key.replace('-', '_')) for key in
                      ('overlay', 'native-source-root', 'stlport-root', 'native-static', 'jdk')}
            argv = command(case, bindings, args.folder, args.binary, native, args.bot_console, args.retirement_console)
            print('TEST ' + data['id'] + '/' + case['id'], flush=True)
            row = {'id': case['id'], 'kind': case['kind'], 'seconds': time.monotonic()-start,
                   'exit_code': None, 'passed': False}
            try:
                with (output / (case['id'] + '.log')).open('x') as log:
                    code, timed_out = execute(argv, log, timeout=2400 if case['kind'] in ('rryatt_linked','rryatt_recovery','rryatt_group','retirement_offline_recovery') else 1200)
                row.update(exit_code=code, timed_out=timed_out, passed=code == 0 and not timed_out)
                if row['passed'] and case['kind'] not in ('driver_unit', 'native_gate'):
                    row['artifact'] = runtime_artifact(output/(case['id']+'.log'), args.folder)
                row['log_sha256'] = hashlib.sha256((output/(case['id']+'.log')).read_bytes()).hexdigest()
            except Exception as exc:
                row['error'] = str(exc)
                row['passed'] = False
            row['seconds'] = time.monotonic()-start
            report['cases'].append(row)
            print(json.dumps(row), flush=True)
            if not row['passed']:
                break
        report['passed'] = len(report['cases']) == len(data['tests']) and all(c['passed'] for c in report['cases'])
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        xml = ET.Element('testsuite', name=data['id'], tests=str(len(data['tests'])),
                         failures=str(sum(not c['passed'] for c in report['cases'])),
                         skipped=str(len(data['tests'])-len(report['cases'])))
        for case in data['tests']:
            row = next((r for r in report['cases'] if r['id'] == case['id']), None)
            child = ET.SubElement(xml, 'testcase', name=case['id'], classname=data['id'], time=str(row['seconds'] if row else 0))
            if row and not row['passed']:
                ET.SubElement(child, 'failure', message='See retained case log')
            elif not row:
                ET.SubElement(child, 'skipped', message=report.get('error', 'Prior case failed'))
        ET.ElementTree(xml).write(output / 'junit.xml', encoding='utf-8', xml_declaration=True)
        print('Test-set evidence: ' + str(output), flush=True)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
