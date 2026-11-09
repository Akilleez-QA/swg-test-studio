#!/usr/bin/env python3
"""Saved ELF64 production-component gates, separate from wire/visual acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

GATES = {
    'encounter_census_database': ('encounter_census_database',),
    'encounter_inventory_database': ('encounter_inventory_database','encounter_disposal_database','encounter_transient_database','encounter_load_graph_database'),
    'encounter_release_database': ('encounter_release_database','encounter_offline_database'),
    'encounter_cleanup': ('encounter_epochs','encounter_leases','encounter_variables','encounter_census_query','encounter_census_exchange','encounter_native_census','encounter_writer_fence','encounter_native_writer','encounter_grants','encounter_root_claim','encounter_root_claim_actions','encounter_claim_receiver','encounter_root_source','private_root_claim','dungeon_root_claim','dungeon_entry_routing','encounter_bootstrap','encounter_bootstrap_actions','encounter_census_coordinator','encounter_census_actions','encounter_census_prefix','encounter_census_persistence','encounter_census_frames','encounter_object_origins','encounter_origin_fixture','encounter_cleanup','encounter_save_wire','encounter_save_book','encounter_save_bounds','encounter_save_persistence','encounter_release_query','encounter_save_frames','encounter_save_coordinator'),
    'hosted_complete': ('hosted_public_contract','hosted_snapshot_contract','hosted_public_policy','hosted_public_sampler',
        'hosted_snapshot_sampler','hosted_snapshot_capacity','hosted_mixed_capacity','main_rryatt_bridge',
        'capacity_registration','dungeon_initialization_cleanup','hosted_publishers','public_publishers',
        'hosted_public_fixture','hosted_public_driver_actions','hosted_public_group','hosted_public_live',
        'hosted_public_surface','hosted_public_reconnect','encounter_leases','encounter_variables','encounter_census_query','encounter_census_exchange','encounter_native_census','encounter_writer_fence','encounter_native_writer','encounter_grants','encounter_root_claim','encounter_root_claim_actions','encounter_claim_receiver','encounter_root_source','private_root_claim','dungeon_root_claim','dungeon_entry_routing','encounter_bootstrap','encounter_bootstrap_actions','encounter_census_coordinator','encounter_census_actions','encounter_census_prefix','encounter_census_persistence','encounter_census_frames','encounter_object_origins','encounter_origin_fixture','encounter_cleanup','encounter_save_wire','encounter_save_book','encounter_save_bounds','encounter_save_persistence','encounter_release_query','encounter_save_frames','encounter_save_coordinator','group_admission_evidence','private_exit_completion','hosted_public_preparation','hosted_public_config','hosted_admission_config','hosted_public_selection','group_travel_begin','source_input_verification','protocol_bot_console'),
    'world_driver_actions': ('world_driver_actions','whole_world_live','protocol_bot_console','world_family_fixture'),
    'whole_world_families': ('world_runtime_policy','world_family_fixture','instance_maintenance','world_entry_routes','fixture_journal_maintenance','instance_scope','all_world_admission','all_world_recovery',
                            'all_world_login','all_world_control','world_maintenance','retirement_family_content','retirement_cohort_authority',
                            'login_attempt_routes','login_attempt_admission','login_journal','login_load_ack',
                            'login_reply','login_snapshots','login_presence','login_transfers','falcon_login_recovery',
                            'falcon_session_recovery','rryatt_login_recovery','group_entry_preparation',
                            'group_transfer_placement','group_transfer_dispatch','login_family_dispatch','scene_publication'),
    'scene_publication': ('scene_publication','client_handoff','zone_instance_control','cold_scene_wire','login_load_ack'),
    'private_callbacks': ('private_group_access','private_actor_context','private_actor_observation','private_remote_admission','private_close_response','working_opening_session','working_failure_session','instance_entry_routing','private_uplink_session','sequencer_spawn_session','valley_cleanup_session','private_close_session','private_instance_sessions','private_instance_admission','content_capacity'),
    'hosted_readiness': ('hosted_content_readiness','hosted_capacity_returns','hosted_capacity_layout','hosted_content_layout','authored_publisher','hosted_selection_poll','hosted_family_capacity','zone_instance_lifecycle'),
    'hosted_layout': ('hosted_selection_poll','hosted_capacity_layout','hosted_content_layout','authored_publisher','content_capacity','private_instance_sessions','private_lease_observation'),
    'hosted_capacity': ('hosted_selection_poll','protocol_bot_console','hosted_family_capacity','instance_selection','zone_instance_lifecycle','content_capacity','instance_admission_capacity'),
    'private_leases': ('private_instance_sessions','private_content_lease','private_lease_observation','content_capacity','instance_admission_capacity','content_registry_wire','private_instance_admission'),
    'private_admission': ('private_group_access','instance_entry_routing','private_instance_admission','registered_controller_routing','solo_eligibility'),
    'authored_families': ('capacity','hosted_content','template_controller_evidence','instance_scope','runtime_policy','rryatt_runtime_policy','zone_instance_identity','zone_instance_lifecycle'),
    'retirement_fault_services': ('fixture_central_signal','fixture_service_signal','retirement_fault_targets','retirement_fault_boundary','central_loss_recovery'),
    'retirement_cohort': ('retirement_cohort_seats','retirement_cohort_authority','retirement_cohort_routing','retirement_cohort_admission','retirement_event','retirement_evidence_sharing','retirement_profile','retirement_shared_snapshot','retirement_snapshot_owner','retirement_placement','retirement_forwarding','world_shutdown_begin','admission_player_position','contained_pilot_scheduling','pending_space_arrival_recovery'),
    'private_sessions': ('private_group_access','instance_entry_routing','private_instance_admission','falcon_travel','ship_interior_save','scene_position_save','scene_position_wire','falcon_expiry_fixture','falcon_login_recovery','falcon_session_recovery','recovery_room_timer','dungeon_session_expiry','solo_eligibility','group_consolidation_room','instance_login_validation'),
    'distributed_shutdown': ('fixture_retirement_signal','retirement_family_content','world_shutdown_wire','world_shutdown_supervisor','world_shutdown_central','world_shutdown_begin','world_worker_freeze','world_freeze_receiver','worker_freeze_flush','frozen_tcp_flush','world_launch_fence','supervisor_launch_paths','process_spawner','world_save_frame','world_save_persistence','zone_instance_retirement'),
    'worker_supervisor': ('world_worker_freeze','world_freeze_receiver','worker_freeze_flush','frozen_tcp_flush','world_launch_fence','supervisor_launch_paths','process_spawner','world_save_frame','world_save_persistence','zone_instance_retirement'),
    'world_save': ('world_save_wire','world_save_book','world_save_persistence','world_save_coordinator','world_save_frame','commodities_save_commit','login_save_barrier','rryatt_demand_group'),
    'retirement_foundation': ('zone_instance_retirement_policy','zone_instance_retirement','zone_instance_lifecycle','zone_instance_journal','rryatt_layout','rryatt_demand_group','group_transfer_placement','group_transfer_quiet','pending_arrival_recovery','login_save_barrier'),
    'rryatt_demand_fault': ('fixture_rryatt_signal','rryatt_login_recovery','pending_arrival_recovery','pending_arrival_receivers','completed_login_loads','rryatt_demand_group','zone_instance_lifecycle','zone_instance_journal','rryatt_capacity'),
    'rryatt_demand': ('rryatt_login_recovery','rryatt_demand_group','rryatt_layout','rryatt_readiness','rryatt_runtime_policy','instance_readiness','kashyyyk_host_policy','stage6_release_evidence','package_comparison64','rryatt_capacity','group_linked_preflight','login_family_dispatch','admission_capacity_wire','pending_arrival_recovery','pending_arrival_receivers','rryatt_registered','rryatt_group','group_entry_preparation'),
    'rryatt_fault': ('protocol_bot_scope','fixture_worker_signal','completed_login_loads','pending_arrival_recovery','pending_arrival_receivers','rryatt_group','rryatt_recovery'),
    'rryatt_capacity': ('protocol_bot_gate_cycles','protocol_companions','rryatt_capacity','instance_admission_capacity','instance_admission_reservations','group_instance_admission','rryatt_group','group_entry_preparation'),
    'public_group': ('rryatt_entry','protocol_bot_enemy','client_handoff','group_linked_preflight','protocol_ground_combat','rryatt_group','group_instance_routing','group_entry_preparation','capacity_combat','group_transfer_quiet','combat_protection_paths'),
    'kashyyyk': ('rryatt_guide_floating', 'protocol_bot_approach', 'rryatt_clone_menu', 'protocol_unstick', 'protocol_bot_death', 'rryatt_recovery', 'rryatt_guide', 'rryatt_entry', 'rryatt_registered', 'registered_controller_routing'),
    'capacity': ('instance_admission_capacity', 'instance_admission_reservations',
                 'group_instance_admission', 'group_capacity_rosters', 'fixed_host_capacity',
                 'cold_start_policy', 'solo_eligibility', 'group_travel_requests',
                 'zone_instance_lifecycle', 'zone_instance_journal'),
    'combat': ('clock_precision','capacity_combat', 'group_transfer_quiet', 'group_entry_boundary',
               'group_entry_frame_timing', 'delayed_instance_warp', 'group_transfer_placement',
               'combat_protection_paths'),
    'recovery': ('pending_arrival_recovery', 'admission_transfer_journal', 'login_family_dispatch',
                 'group_transfer_dispatch', 'pending_arrival_receivers', 'pending_space_arrival_recovery', 'admission_player_position', 'contained_pilot_scheduling', 'ready_player_location', 'group_login_cleanup',
                 'space_ship_relogin', 'fighter_pilot_create', 'consolidation_abort_retry', 'login_scene_hint',
                 'login_attempt_admission', 'login_presence', 'login_database_peers', 'login_load_ack',
                 'login_snapshots', 'login_save_barrier', 'login_journal'),
    'routing': ('group_instance_routing', 'group_consolidation_events', 'friend_finder_routing',
                'public_station_routing', 'ord_space_routing', 'ord_login_recovery',
                'quest_retrieval_ids', 'tutorial_sequence', 'falcon_timeout')}

GATES['encounter_exact_load'] = ('encounter_load_wire','encounter_load_persistence','encounter_load_locator','encounter_load_batches','encounter_load_coordinator','encounter_load_native','encounter_load_snapshot','encounter_load_dispatch','encounter_load_unload','encounter_load_fixture','encounter_load_actions','encounter_load_graph','encounter_load_graph_query','encounter_discovery_task','protocol_bot_console')
GATES['encounter_offline'] = ('encounter_offline','encounter_offline_query','encounter_release_query','encounter_save_wire','encounter_save_book','encounter_save_bounds','encounter_save_persistence','encounter_save_coordinator','encounter_discovery_coordinator','encounter_load_coordinator','encounter_inventory','encounter_native_possessions','encounter_offline_actions','encounter_release_fixture','protocol_bot_console','protocol_suite_selection')
GATES['encounter_withdrawal'] = ('encounter_withdrawal_coordinator','encounter_withdrawal_actions','encounter_enrollment_coordinator','encounter_census_coordinator','world_shutdown_begin','world_shutdown_central','worker_freeze_flush','world_worker_freeze','world_shutdown_supervisor','zone_instance_retirement')
for _gate in ('encounter_withdrawal','distributed_shutdown','hosted_complete','whole_world_families'):
    GATES[_gate] += ('worker_removal',)
GATES['encounter_enrollment'] = ('encounter_enrollment','encounter_enrollment_native','encounter_enrollment_coordinator','encounter_bootstrap','encounter_census_frames','encounter_root_claim','encounter_close_coordinator','zone_instance_lifecycle','encounter_enrollment_actions')
GATES['ground_recovery'] = ('ground_authored_cell','ground_cell_recovery','mount_logout',
    'all_world_recovery','ord_login_recovery','falcon_login_recovery','rryatt_login_recovery',
    'scene_position_save','login_snapshots','protocol_suite_selection','ground_buildout_identity','ground_cell_fixture','ground_cell_actions','protocol_bot_console')
GATES['hosted_login'] = ('hosted_login_contract','hosted_exit_source','hosted_exit_recovery',
    'hosted_login_cleanup','hosted_login_routes','hosted_login_dispatch','hosted_public_login_placement','hosted_public_login_recovery','hosted_public_admission','login_family_dispatch','login_attempt_routes','ord_login_recovery',
    'ground_cell_recovery','falcon_login_recovery','rryatt_login_recovery',
    'login_snapshots','login_save_barrier','scene_publication')
GATES['hosted_login'] += ('hosted_public_instances_fixture','hosted_local_warp','hosted_public_login','hosted_admission_collector','hosted_public_pending_login','hosted_public_home')
GATES['hosted_login'] += ('hosted_public_maintenance',)
GATES['hosted_login'] += ('hosted_private_receipt','hosted_saved_context','hosted_login_context_query','hosted_saved_context_wire')
GATES['hosted_login'] += ('encounter_variables','hosted_private_variables')
GATES['hosted_login'] += ('hosted_login_context_task',)
GATES['hosted_login'] += ('hosted_parent_exit',)
GATES['hosted_login'] += ('hosted_private_resume_source',)
GATES['hosted_login'] += ('hosted_private_entry_contract','hosted_private_room_state','hosted_private_room_variables','hosted_private_room_binding')
GATES['hosted_login'] += ('hosted_private_capacity_wire','hosted_private_sampler')
GATES['hosted_login'] += ('hosted_private_capacity',)
GATES['hosted_login'] += ('capacity_wire_contract','hosted_private_entry_evidence')
GATES['hosted_login'] += ('hosted_private_entry_wire',)
GATES['hosted_login'] += ('hosted_private_preparation',)
GATES['hosted_login'] += ('hosted_private_original_dispatch','hosted_private_original_access')
GATES['private_arrival'] = ('hosted_private_arrival_storage','private_arrival_publication','private_arrival_coordinator',
    'scene_publication','world_save_wire','world_save_frame','world_save_coordinator','world_save_book','world_save_persistence','world_shutdown_wire','world_shutdown_central')
GATES['hosted_login'] += ('hosted_private_arrival_storage','private_arrival_publication','private_arrival_coordinator')
GATES['private_resume_foundation'] = ('private_login_dispatch','private_login_wire','private_resume_permission','private_resume_original_access','login_family_dispatch','hosted_private_arrival_storage')
GATES['hosted_login'] += ('private_login_dispatch','private_login_wire','private_resume_permission','private_resume_original_access')
GATES['private_resume_foundation'] += ('private_resume_wire','private_resume_receiver','private_resume_decisions')
GATES['hosted_login'] += ('private_resume_wire','private_resume_receiver','private_resume_decisions')
GATES['private_retained_login'] = GATES['private_resume_foundation'] + ('private_login_policy','private_login_route','private_saved_session_closed','private_arrival_coordinator','private_arrival_publication')
GATES['hosted_login'] += ('private_login_policy','private_login_route','private_saved_session_closed')
GATES['private_retained_login'] += ('hosted_private_warp',)
GATES['hosted_login'] += ('hosted_private_warp',)
GATES['private_arrival'] += ('private_scene_transfer',)
GATES['private_retained_login'] += ('private_scene_transfer',)
GATES['hosted_login'] += ('private_scene_transfer',)
for _gate in ('private_arrival','private_retained_login','hosted_login'):
    GATES[_gate] += ('private_arrival_access',)
    GATES[_gate] += ('public_arrival_placement',)
    GATES[_gate] += ('private_arrival_notices',)
    GATES[_gate] += ('private_arrival_login','private_publication_ack')
for _gate in ('private_arrival','private_retained_login','hosted_login','scene_publication','whole_world_families'):
    GATES[_gate] += ('observation_publication',)
for _gate in ('private_arrival','private_retained_login','hosted_login','scene_publication','hosted_complete'):
    GATES[_gate] += ('private_client_lifecycle',)
GATES['private_client_lifecycle'] = ('private_client_lifecycle','private_arrival_publication','scene_publication')
for _gate in ('private_arrival','private_retained_login','hosted_login','hosted_complete','private_client_lifecycle'):
    GATES[_gate] += ('private_caller_startup',)
GATES['private_caller_startup'] = ('private_caller_startup','encounter_object_origins','hosted_private_original_dispatch')
for _gate in ('private_arrival','private_retained_login','hosted_login','hosted_complete','private_client_lifecycle'):
    GATES[_gate] += ('private_placement_attachment',)
GATES['private_placement_attachment'] = ('private_placement_attachment','scene_publication','private_arrival_access')
GATES['private_active_join']=('private_active_join','private_active_join_actions','instance_entry_routing','private_remote_admission','private_root_claim')
GATES['private_group_selection']=('private_group_selection','hosted_private_entry_evidence','group_instance_routing','private_group_access')
GATES['private_choice_preparation']=('private_claim_affinity','private_choice_wire','private_choice_reference','private_choice_coordinator','private_choice_root_preflight','private_choice_handoff','private_choice_requests','private_choice_worker','private_source_unload','private_choice_callbacks','private_group_selection','hosted_private_entry_wire','private_group_access')
GATES['private_choice_preparation'] += ('private_choice_claim_pipeline',)
GATES['private_choice_preparation'] += ('private_choice_jni',)
GATES['dungeon_choice_routes']=('dungeon_choice_routes','dungeon_choice_discovery','dungeon_choice_consent','dungeon_root_claim','dungeon_entry_routing','hosted_private_original_access')
GATES['private_choice_preparation'] += ('dungeon_choice_routes',)
GATES['private_choice_preparation'] += ('dungeon_choice_discovery',)
GATES['private_choice_preparation'] += ('dungeon_choice_consent',)
GATES['dungeon_group_choices']=('dungeon_group_choices','dungeon_choice_discovery','dungeon_choice_consent',
    'hosted_private_original_access','private_group_selection','private_choice_worker','private_source_unload')
GATES['dungeon_choice_routes'] += ('dungeon_group_choices',)
GATES['private_choice_preparation'] += ('dungeon_group_choices',)
GATES['private_choice_pressure']=('private_choice_pressure','private_claim_pressure')
GATES['private_choice_preparation'] += GATES['private_choice_pressure']
GATES['private_choice_metadata']=('private_choice_metadata','private_choice_jni')
GATES['dungeon_choice_retry']=('dungeon_choice_retry','dungeon_choice_discovery','dungeon_group_choices',
    'zone_cwd_callbacks','private_choice_worker','private_source_unload')
GATES['private_choice_preparation'] += ('private_choice_metadata','dungeon_choice_retry','zone_cwd_callbacks')
GATES['private_consolidation'] = ('private_group_placement','private_consolidation_requests',
    'private_consolidation_scripts','private_resident_permission','private_resident_original_access',
    'private_crew_quiet','private_source_unload','private_group_selection','private_entry_reply',
    'group_consolidation_room','hosted_private_entry_wire','group_transfer_placement','consolidation_abort_retry','dungeon_consolidation',
    'private_resume_capacity','private_consolidation_finalize','private_continuation_storage')
GATES['private_consolidation_transaction'] = ('private_consolidation_scripts','dungeon_consolidation',
    'private_consolidation_finalize','private_continuation_storage','private_consolidation_requests',
    'private_arrival_access','private_source_unload','hosted_private_variables')
GATES['private_departure_transaction'] = ('private_departure_storage','private_departure_executor',
    'private_departure_scripts','private_departure_coordinator','private_departure_receiver',
    'private_departure_journal','private_departure_registration','private_source_binding')
GATES['private_departure_recovery'] = GATES['private_departure_transaction']
GATES['private_crew'] = ('private_group_exclusivity','private_crew_wire','private_crew_reference',
    'private_crew_journey','private_crew_requests','private_crew_projection','private_crew_coordinator','private_crew_worker','dungeon_crew_choices',
    'hosted_private_entry_evidence','private_group_selection','private_claim_affinity')
GATES['private_group_selection'] += ('private_group_exclusivity',)
GATES['private_consolidation'] += GATES['private_departure_transaction']
GATES['private_consolidation_transaction'] += GATES['private_departure_transaction']
GATES['private_choice_preparation'] += GATES['private_consolidation']
for _gate in ('private_admission','private_sessions','hosted_login','hosted_complete'):
    GATES[_gate] += ('private_active_join','private_active_join_actions')
    GATES[_gate] += ('private_group_selection',)
    GATES[_gate] += ('private_claim_affinity','private_choice_wire','private_choice_coordinator','private_choice_requests','private_choice_worker')
    GATES[_gate] += ('private_choice_reference','private_choice_root_preflight','private_choice_handoff','private_choice_callbacks')
    GATES[_gate] += ('private_choice_claim_pipeline',)
    GATES[_gate] += ('private_choice_jni',)
    GATES[_gate] += ('dungeon_choice_routes',)
    GATES[_gate] += ('dungeon_choice_discovery',)
    GATES[_gate] += ('dungeon_choice_consent',)
    GATES[_gate] += ('dungeon_group_choices',)
    GATES[_gate] += GATES['private_choice_pressure']
    GATES[_gate] += ('private_choice_metadata','dungeon_choice_retry','zone_cwd_callbacks')
    GATES[_gate] += GATES['private_consolidation']
GATES['private_initial_recovery'] = ('private_recovery_wire','private_recovery_source','private_recovery_dispatch','private_recovery_target',
    'private_source_cancel','private_source_cancel_receiver','private_source_cancel_coordinator','terminal_transfer_ack','terminal_transfer_authority',
    'private_source_unload',
    'terminal_marker_cleanup','terminal_marker_receiver',
    'private_login_route','private_arrival_coordinator','private_arrival_access','private_arrival_login',
    'pending_arrival_recovery','pending_arrival_receivers','completed_login_loads','login_presence')
GATES['hosted_login'] += tuple(name for name in GATES['private_initial_recovery'] if name not in GATES['hosted_login'])
GATES['hosted_login'] += tuple(name for name in GATES['private_crew'] if name not in GATES['hosted_login'])
for _gate in ('hosted_login','capacity','retirement_cohort'):
    GATES[_gate] += ('admission_collection_phase',)
GATES['admission_collection'] = ('hosted_admission_collector','admission_collection_phase','hosted_private_preparation',
    'retirement_evidence_sharing','retirement_snapshot_owner','group_entry_preparation','group_admission_evidence',
    'instance_admission_capacity','instance_admission_reservations','group_instance_admission','retirement_cohort_admission','group_transfer_dispatch')
_pressure=('admission_capacity_sharing','admission_capacity_reclamation','admission_scope_pressure',
           'admission_source_exclusive','admission_group_history','admission_queue_window','admission_plan_bounds')
GATES['admission_pressure']=_pressure+('hosted_admission_collector','retirement_evidence_sharing',
    'instance_admission_capacity','instance_admission_reservations','group_entry_preparation','group_entry_boundary')
for _gate in ('admission_collection','capacity','hosted_complete','hosted_login'):
    GATES[_gate] += _pressure
GATES['hosted_private_fixture'] = ('hosted_private_instances_fixture','hosted_private_mtp_actions','private_active_join_actions','private_actor_context','private_actor_observation','protocol_fixture_compile','protocol_suite_selection')
GATES['private_ship_fixture'] = ('private_crew_fixture_policy','private_crew_ship_fixture','private_ship_round_trip','public_cell_publication','capacity_player_world','protocol_bot_console','protocol_fixture_compile')
GATES['public_cell_publication'] = ('public_cell_publication','hosted_local_warp','hosted_private_warp','scene_publication','client_handoff')
GATES['private_group_fixture'] = ('private_group_fixture','private_departure_journal','private_departure_storage')
GATES['pilot_presence'] = ('capacity_player_world','capacity_combat','combat_protection_paths')
GATES['private_passenger_fixture'] = ('private_ship_passenger_fixture',)
GATES['hosted_login'] += ('public_cell_publication','capacity_player_world')
GATES['hosted_complete'] += ('capacity_wire_contract',)
GATES['private_admission'] += ('private_entry_reply',)
GATES['private_admission'] += ('hosted_private_original_dispatch','hosted_private_original_access')
GATES['private_admission'] += ('private_lease_collection',)
GATES['whole_world_families'] += ('ground_authored_cell','ground_cell_recovery','mount_logout')
GATES['ground_group'] = ('group_admission_evidence','group_transfer_placement','group_transfer_dispatch',
    'pending_arrival_receivers','group_consolidation_room','all_world_admission','ground_authored_cell','ground_cell_recovery',
    'retirement_placement','retirement_cohort_authority','ground_group_actions','protocol_suite_selection')
GATES['encounter_automatic'] = ('encounter_automatic_actions','encounter_root_claim_workflow','encounter_automatic_bootstrap','encounter_bootstrap','encounter_census_coordinator',
    'encounter_enrollment_coordinator','encounter_withdrawal_coordinator','worker_removal',
    'zone_instance_lifecycle','login_attempt_admission','login_scene','protocol_suite_selection')
for _gate in ('encounter_cleanup','hosted_complete'):
    GATES[_gate] += ('encounter_enrollment','encounter_enrollment_native','encounter_enrollment_coordinator','encounter_withdrawal_coordinator','encounter_withdrawal_actions')
    GATES[_gate] += ('encounter_automatic_bootstrap','encounter_automatic_actions','encounter_root_claim_workflow')
for _gate in ('encounter_cleanup','hosted_complete'):
    GATES[_gate] += ('encounter_offline','encounter_offline_query','encounter_offline_actions','encounter_release_fixture')

for gate in ('encounter_cleanup', 'hosted_complete'):
    GATES[gate] += ('encounter_load_wire','encounter_load_persistence','encounter_load_locator','encounter_load_batches','encounter_load_coordinator','encounter_load_native','encounter_load_snapshot','encounter_load_dispatch','encounter_load_unload','encounter_load_fixture','encounter_load_actions',)
    GATES[gate] += ('encounter_load_graph','encounter_load_graph_query',)
    GATES[gate] += ('encounter_discovery_wire','encounter_discovery_persistence','encounter_discovery_task','encounter_discovery_frames','encounter_discovery_coordinator',)
    GATES[gate] += ('encounter_close_request','encounter_close_coordinator','encounter_private_drain','encounter_legacy_cleanup','dungeon_session_expiry')
    GATES[gate] += ('encounter_inventory','encounter_disposal_query','encounter_transient')
    GATES[gate] += ('encounter_manifest','encounter_manifest_coordinator')
    GATES[gate] += ('encounter_native_disposal','encounter_disposal_coordinator')
    GATES[gate] += ('encounter_restoration','encounter_restore_coordinator','encounter_restore_scripts')
    GATES[gate] += ('encounter_recovery','encounter_recovery_coordinator','encounter_recovery_receiver','encounter_recovery_actions','encounter_reuse_actions')
    GATES[gate] += ('encounter_native_authored', 'encounter_native_possessions', 'encounter_closing', 'encounter_trigger', 'zone_cwd_callbacks')
    GATES[gate] += ('encounter_birth', 'encounter_message_envelope', 'encounter_callbacks', 'encounter_message_persistence', 'encounter_message_dispatch', 'protocol_suite_selection', 'encounter_census_lifecycle', 'encounter_authored_objects', 'encounter_authored_catalog', 'encounter_authored_grants')


for _gate in ('hosted_readiness','hosted_complete'):
    GATES[_gate] += ('hosted_return_collector',)
GATES['hosted_readiness'] += ('hosted_public_contract','hosted_public_policy','hosted_mixed_capacity')

GATES['single_world'] = ('instance_scope','world_runtime_policy','world_family_fixture',
    'main_rryatt_bridge','all_world_login','all_world_admission','all_world_control',
    'encounter_enrollment','protocol_bot_console','kachirho_single_actions')
GATES['fixture_scripts'] = ('protocol_fixture_compile','cloning_initialization')
GATES['single_world'] += ('protocol_fixture_compile',)
GATES['hosted_complete'] += ('protocol_fixture_compile',)
GATES['console_worker_routing'] = ('console_worker_routing',)
GATES['console_frames'] = ('console_frames',)
GATES['heroic_group_ownership'] = ('heroic_group_ownership','heroic_group_arrival',
    'heroic_group_membership','heroic_group_ejection','hosted_private_room_state',
    'hosted_private_entry_evidence','private_group_exclusivity','hosted_private_arrival_storage',
    'private_arrival_access','private_resume_wire','private_resume_receiver',
    'private_resume_decisions','private_login_route','instance_login_validation')
GATES['heroic_live_fixture'] = ('heroic_group_live','heroic_inspection_scope','protocol_bot_console','protocol_fixture_compile','protocol_suite_selection')
GATES['hoth_heroic_fixture'] = ('hoth_heroic_fixture','heroic_group_live','heroic_inspection_scope','protocol_bot_console',
    'protocol_fixture_compile','protocol_suite_selection','heroic_group_membership','private_area_placement','private_departure_executor','content_capacity','heroic_hoth_prerequisites')
GATES['hosted_login'] += ('heroic_group_ownership','heroic_group_arrival','heroic_group_membership','heroic_group_ejection','instance_login_validation')
for _gate in ('hosted_login','hosted_complete'):
    GATES[_gate] += ('console_worker_routing','console_frames')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gate', choices=tuple(GATES), required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--native-source-root', type=Path, required=True)
    parser.add_argument('--stlport-root', type=Path, required=True)
    parser.add_argument('--native-static', type=Path, required=True)
    parser.add_argument('--jdk', type=Path, required=True)
    args = parser.parse_args()
    overlay = args.overlay.resolve(strict=True)
    native = ['--stlport-root', str(args.stlport_root), '--native-central', str(overlay/'bin/CentralServer'),
              '--native-source-root', str(args.native_source_root), '--native-static', str(args.native_static)]
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(overlay/'lib') + ':' + env.get('LD_LIBRARY_PATH', '')
    for name in GATES[args.gate]:
        path = Path(__file__).with_name('test_' + name + '.py')
        # Only the shared native harness accepts producer arguments. Extracted
        # production-method probes own their explicit -m64 compiler commands.
        text = path.read_text()
        command = [sys.executable, str(path)]
        if ('from test_login_recovery import main' in text or name=='private_choice_claim_pipeline' or
            'from admission_pressure_probe import run_pressure' in text or
            'from test_hosted_private_arrival_storage import run_probe' in text or
            name in ('private_resident_permission','private_resume_wire','private_resume_receiver','private_login_wire','private_resume_permission','private_arrival_publication','encounter_automatic_bootstrap','encounter_withdrawal_coordinator','encounter_enrollment_coordinator','encounter_grants','encounter_root_claim','encounter_claim_receiver','encounter_census_lifecycle','encounter_authored_grants','encounter_close_request','encounter_close_coordinator','encounter_discovery_coordinator','encounter_manifest_coordinator','encounter_disposal_coordinator','encounter_restore_coordinator','encounter_recovery_coordinator','encounter_recovery_receiver','encounter_transient_database','encounter_load_graph_database','encounter_load_persistence','encounter_load_coordinator','encounter_offline_database')):
            command += native
        if name in ('client_handoff','scene_publication','cold_scene_wire','hosted_snapshot_capacity','hosted_mixed_capacity'):
            command += ['--native-library', str(overlay/'lib/libserverNetworkMessagessharedgameConnectionServer.so')]
        if name=='hosted_mixed_capacity':command += native
        if name in ('protocol_fixture_compile','private_choice_jni','private_ship_passenger_fixture'):command += ['--classes',str(overlay/'classes')]
        if name=='private_choice_jni':command += ['--native-library',str(overlay/'lib/libserverScript.so')]
        if name in ('encounter_release_query','encounter_release_database','encounter_census_query','encounter_census_database','encounter_inventory','encounter_inventory_database','encounter_disposal_query','encounter_disposal_database','encounter_transient','encounter_transient_database','encounter_load_graph_query','encounter_load_graph_database','encounter_offline_query','encounter_offline_database'):
            # Query/row probes need the actual DB bind/OCI producers, without
            # application-only CMLoader symbols from the full server library.
            for part in ('sharedqueue','sharedcore','src_oci'):
                command += ['--native-library',str(overlay/'lib'/('libsharedDatabaseInterface'+part+'.so'))]
        if name in ('capacity_registration','dungeon_initialization_cleanup','hosted_publishers','encounter_restore_scripts'):
            command += ['--jdk',str(args.jdk)]
        if name=='public_publishers':command += ['--owned-queries']
        if "'--java'" in text or name in ('encounter_private_drain','dungeon_choice_routes','dungeon_choice_discovery','dungeon_group_choices','dungeon_choice_retry','dungeon_consolidation','dungeon_crew_choices'):
            command += ['--java', str(args.jdk/'bin/java')]
        print(json.dumps({'gate': args.gate, 'probe': name,
                          'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}), flush=True)
        subprocess.run(command, env=env, check=True, timeout=180)


if __name__ == '__main__':
    main()
