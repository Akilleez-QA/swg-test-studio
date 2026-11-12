"""Bytes printed by the held peer's --encode mode; see ClientWireTests in test_client_actions.py.

Recorded with `driver --encode <character> <sequence> <verb> [args]` (devtools/zones/protocol_driver64.cpp,
encodeClientAction), built with SWG_STUDIO_PROFILE_RESTORATION and linked against the restoration tree's shared
libraries. The messages are the tree's own classes. Re-record after changing the peer; source_sha256 is checked.
"""

WIRE = {
    "character": '8800000000012345',
    "sequence": 7,
    "source_sha256": '679429dc7181fdf9c2d6d8b0c23ef0402f47d62dd5b9978eff2a09461dbe6df6',
    "messages": [
        {"verb": 'tradeRequest', "args": ['8800000000067890'],
         "hex": '0500465ece802300000015010000393006aa8d431f0000000000000000000000000000000000320907aa8d431f00'},
        {"verb": 'tradeAccept', "args": [],
         "hex": '0500465ece802300000015010000393006aa8d431f00000000000200000000000000000000000000000000000000'},
        {"verb": 'tradeDeny', "args": [],
         "hex": '0500465ece802300000015010000393006aa8d431f00000000000300000000000000000000000000000000000000'},
        {"verb": 'tradeItem', "args": ['9123456789012'],
         "hex": '020056138d1e14aa66384c080000'},
        {"verb": 'tradeCredits', "args": ['500'],
         "hex": '0200e87e52d1f4010000'},
        {"verb": 'tradeOffer', "args": [],
         "hex": '010017ca31b1'},
        {"verb": 'tradeUnoffer', "args": [],
         "hex": '010082431ee8'},
        {"verb": 'tradeVerify', "args": [],
         "hex": '0100ee47e29a'},
        {"verb": 'tradeReject', "args": [],
         "hex": '01007086c26e'},
        {"verb": 'tradeCancel', "args": [],
         "hex": '0100980fa89c'},
        {"verb": 'groupInvite', "args": ['8800000000067890', 'Capabcdefghijkl'],
         "hex": ('0500465ece802300000016010000393006aa8d431f000000000007000000585d508800000000000000000f0000004300'
                 '610070006100620063006400650066006700680069006a006b006c00')},
        {"verb": 'groupJoin', "args": ['8800000000067890', 'Capabcdefghijkl'],
         "hex": '0500465ece802300000016010000393006aa8d431f00000000000700000007689ea9320907aa8d431f0000000000'},
        {"verb": 'groupDecline', "args": [],
         "hex": '0500465ece802300000016010000393006aa8d431f0000000000070000004ff8e143000000000000000000000000'},
        {"verb": 'groupLeave', "args": [],
         "hex": '0500465ece802300000016010000393006aa8d431f00000000000700000054d66150000000000000000000000000'},
        {"verb": 'groupDisband', "args": [],
         "hex": '0500465ece802300000016010000393006aa8d431f0000000000070000003a2dd246000000000000000000000000'},
        {"verb": 'groupUninvite', "args": ['8800000000067890', 'Capabcdefghijkl'],
         "hex": '0500465ece802300000016010000393006aa8d431f0000000000070000007fa4262e320907aa8d431f0000000000'},
        {"verb": 'groupMakeLeader', "args": ['8800000000067890', 'Capabcdefghijkl'],
         "hex": '0500465ece802300000016010000393006aa8d431f00000000000700000084d59a93320907aa8d431f0000000000'},
        {"verb": 'groupDismiss', "args": ['8800000000067890', 'Capabcdefghijkl'],
         "hex": '0500465ece802300000016010000393006aa8d431f0000000000070000003b05502f320907aa8d431f0000000000'},
        {"verb": 'tell', "args": ['8800000000067890', 'Capabcdefghijkl', 'Hello there, partner!'],
         "hex": ('0500f721bb84000000000f004361706162636465666768696a6b6c15000000480065006c006c006f0020007400680065'
                 '00720065002c00200070006100720074006e006500720021000000000007000000')},
    ],
}
