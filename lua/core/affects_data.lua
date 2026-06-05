local M = {}

M.affects = {
    ["sanctuary"] = {
        type         = "spell",
        duration     = 270,
        initString_1 = "^You start glowing.$",
        initString_2 = "^Your aura glows more intensely.$",
        dropString_1 = "^The white aura around your body fades.$",
    },

    ["breath of briskness"] = {
        type         = "spell",
        duration     = 180,
        initString_1 = "^An energy begins to flow within your legs as your body becomes lighter.$",
        initString_2 = "^The energy in your legs is refreshed.$",
        dropString_1 = "^Your legs feel heavier.$",
    },

    ["shield"] = {
        type         = "spell",
        duration     = 1560,
        initString_1 = "^You feel protected.$",
        initString_2 = "^Your protection is revitalised.$",
        dropString_1 = "^Your magical shield wears off.$",
    },

    ["armour"] = {
        type            = "spell",
        duration        = 1100,
        damage_droppable = true,
        initString_1    = "^A blue transparent wall slowly appears around you.$",
        initString_2    = "^Your magic armour is revitalised.$",
        dropString_1    = "^You feel less protected.$",
    },

    ["strength"] = {
        type         = "spell",
        duration     = 1560,
        initString_1 = "^You feel stronger.$",
        initString_2 = "^The duration of the strength spell has been improved.$",
        dropString_1 = "^You feel weaker.$",
    },

    ["detect magic"] = {
        type         = "spell",
        duration     = 2400,
        initString_1 = "^You become sensitive of magical auras.$",
        initString_2 = "^Your awareness of magical auras is renewed.$",
        dropString_1 = "^Your perception of magical auras wears off.$",
    },

    ["bless"] = {
        type         = "spell",
        duration     = 480,
        initString_1 = "^You begin to feel the light of Aman shine upon you.$",
        initString_2 = "^You feel a renewed light shine upon you.$",
        dropString_1 = "^The light of Aman fades away from you.$",
    },

    ["detect evil"] = {
        type         = "spell",
        duration     = 3600,
        initString_1 = "^You feel aware of all that is foul and evil.$",
        initString_2 = "^Your awareness of evil is refreshed.$",
        dropString_1 = "^You sense the red in your vision disappear.$",
    },

    ["sense life"] = {
        type         = "spell",
        duration     = 3200,
        initString_1 = "^You feel your awareness improve.$",
        initString_2 = "^Your awareness is refreshed.$",
        dropString_1 = "^You feel less aware of your surroundings.$",
    },

    ["shroud"] = {
        type         = "spell",
        duration     = 1600,
        damage_droppable = true,
        initString_1 = "^You are surrounded by a misty shroud.$",
        initString_2 = "^Your misty shroud is renewed.$",
        dropString_1 = "^You feel more exposed.$",
    },

    ["night vision"] = {
        type         = "spell",
        duration     = 2650,
        initString_1 = "^Your eyes tingle.$",
        initString_2 = "^Your night vision is refreshed.$",
        dropString_1 = "^Your vision blurs.$",
    },

    ["protection from evil"] = {
        type         = "spell",
        duration     = 1650,
        initString_1 = "^You have a righteous feeling!$",
        initString_2 = "^You feel a renewed righteousness.$",
        dropString_1 = "^You feel less righteous.$",
    },

    ["second wind"] = {
        type         = "buff",
        duration     = 60,
        initString_1 = "^You feel a surge of energy as you gain a second wind.$",
        dropString_1 = "^Your energy wanes as your second wind fades.$",
    },

    ["winded"] = {
        type         = "debuff",
        duration     = 1380,
        initString_1 = "^Your energy wanes as your second wind fades.$",
        dropString_1 = "^You feel less winded.$",
    },

    ["Orkish draught"] = {
        type         = "buff",
        duration     = 120,
        initString_1 = "^The draught burns down your throat, and a fiery feeling fills your limbs.$",
        dropString_1 = "^As the warmth of the draught recedes from your limbs, you feel less energetic.$",
    },

    ["blindness"] = {
        type         = "debuff",
        duration     = 90,
        initString_1 = "^You have been blinded!$",
        dropString_1 = "^You feel a cloak of blindness dissolve.$",
    },

    ["battle glory"] = {
        type         = "buff",
        duration     = 170,
        initString_1 = "^Hearing the horn blow, you feel your urge to battle increase!$",
        dropString_1 = "^You feel your newfound strength leaving you again.$",
    },

    ["miruvor"] = {
        type         = "buff",
        duration     = 180,
        initString_1 = "^You feel a pleasant warmth filling your limbs.$",
        dropString_1 = "^The warmth of the cordial slowly leaves your body.$",
    },

    ["lethargy"] = {
        type         = "debuff",
        duration     = 330,
        initString_1 = "^You feel a sudden loss of energy as the power that once mingled with your own vanishes.$",
        dropString_1 = "^You feel your magic energy coming back to you.$",
    },

    ["tiredness"] = {
        type         = "debuff",
        duration     = 330,
        initString_1 = "^You feel your muscles relax and your pulse slow as the strength that welled within you subsides.$",
        dropString_1 = "^You feel your muscles regain some of their former energy.$",
    },

    ["depression"] = {
        type         = "debuff",
        initString_1 = "^Alas, you realise that yet again the mighty knowledge of drowned Númenor has been lost... Despair settles on you.$",
        dropString_1 = "^Your heart feels lighter.$",
    },

    ["haggardness"] = {
        type         = "debuff",
        duration     = 330,
        initString_1 = "^You feel a sudden flash of dizziness causing you to pause before getting your directional bearings back.$",
        dropString_1 = "^You feel steadier now.$",
    },

    ["growth"] = {
        type         = "buff",
    },

    ["hunger"] = {
        type         = "debuff",
        initString_1 = "^You are hungry.$",
        dropString_1 = "^You are full.$",
        dropString_2 = "^You do not feel hungry anymore.$",
    },

    ["thirst"] = {
        type         = "debuff",
        initString_1 = "^You are thirsty.$",
        dropString_1 = "^You do not feel thirsty anymore.$",
        dropString_2 = "^You are not thirsty anymore.$",
        dropString_3 = "^You feel less thirsty.$",
    },

    ["comfortable"] = {
        type         = "buff",
        initString_1 = "^You feel comfortable.$",
        initString_2 = "^You feel slightly less comfortable.$",
        dropString_1 = "^You no longer feel comfortable.$",
        dropString_2 = "^You're starting to feel very comfortable.$",
    },

    ["very comfortable"] = {
        type         = "buff",
        initString_1 = "^You're starting to feel very comfortable.$",
        dropString_1 = "^You no longer feel very comfortable.$",
        dropString_2 = "^You feel slightly less comfortable.$",
    },

    ["anger"] = {
        type         = "buff",
        duration     = 30,
        initString_1 = "^You are filled with anger!$",
    },

    ["shadow-link"] = {
        type         = "buff",
        initString_1 = "^Your focus sharpens as you share an enslaved shadow",
        initString_2 = "^Your focus sharpens as you share a dreadful warg",
        dropString_1 = "^Your link to the wraith-world disappears.$",
    },

    ["chill touch"] = {
        type         = "debuff",
        initString_1 = "^An icy gust of wind makes you shiver with cold.$",
        dropString_1 = "^You feel warmer.$",
    },

    ["antidote"] = {
        type         = "buff",
        duration     = 540,
        initString_1 = "^A warm feeling runs through your body.$",
        dropString_1 = "^You feel a strange taste in your mouth.$",
    },

    ["heavy burden"] = {
        type         = "debuff",
        initString_1 = "^Your burden is really heavy.$",
        initString_2 = "^Your burden is sheer torture.$",
        dropString_1 = "^Your load feels light.$",
        dropString_2 = "^Your burden is no longer all that heavy.$",
    },

    ["spectral health"] = {
        type         = "buff",
        initString_1 = "^A spectral energy courses through your veins.$",
        initString_2 = "^You completely drain%*$",
        dropString_1 = "^The spectral energy sustaining your health wanes.$",
    },

    ["torpor"] = {
        type         = "debuff",
        duration     = 780,
        initString_1 = "^As you remove the amulet, a cloud descends over your mind.$",
        dropString_1 = "^You feel much better now.$",
    },

    ["Blood of Sauron"] = {
        type         = "buff",
        duration     = 660,
        initString_1 = "^You feel a surge of power.$",
        dropString_1 = "^The warm taste of blood in your mouth vanishes.$",
    },

    ["a pitch-black robe (pale tones)"] = {
        type         = "buff",
        duration     = 30,
        initString_1 = "^You feel energy building up as your robe glows a pale red.$",
        dropString_1 = "^You feel a pale surge of energy flow back into you.$",
    },

    ["a pure white robe (pale tones)"] = {
        type         = "buff",
        duration     = 30,
        initString_1 = "^You feel energy building up as your robe glows a pale white.$",
        dropString_1 = "^You feel a pale surge of energy flow back into you.$",
    },

    ["heightened senses"] = {
        type         = "buff",
        duration     = 270,
        initString_1 = "^You quaff the potion and a pounding fills your head, but it is soon replaced with calm, sharp focus.$",
        dropString_1 = "^Your new-found clarity fades and is replaced by a slight headache.$",
    },

    ["heightened senses (faded)"] = {
        type         = "debuff",
        duration     = 1470,
        initString_1 = "^Your new-found clarity fades and is replaced by a slight headache.$",
        dropString_1 = "^The prickly feeling behind your eyes dissipates.$",
    },

    ["dark aura"] = {
        type         = "buff",
        duration     = 390,
        initString_1 = "^You are surrounded by a murky aura.$",
        dropString_1 = "^The dark aura surrounding you fades.$",
    },

    ["dark aura (faded)"] = {
        type         = "debuff",
        duration     = 1560,
        initString_1 = "^The dark aura surrounding you fades.$",
        dropString_1 = "^The last vestiges of darkness surrounding you dissipates.$",
    },

    ["smothered"] = {
        type         = "buff",
        duration     = 600,
        initString_1 = "^Your lungs seem to burst as%*$",
        dropString_1 = "^The grip on your lungs recedes.$",
    },

    ["shadow-veil"] = {
        type         = "buff",
        duration     = 5700,
        initString_1 = "^You feel your Master's strength join your own.$",
        initString_2 = "^You feel your Master's strength refreshed.$",
        dropString_1 = "^Your Master's strength leaves you.$",
    },

    ["dreaming"] = {
        type         = "debuff",
        duration     = 1260,
        initString_1 = "^As you drink from the murky river, a wave of exhaustion sweeps over you and you are cast into a deep sleep.$",
        dropString_1 = "^A deep fog recedes from your sleep, and you feel once again able to wake.$",
        dropString_2 = "^The visions end abruptly and your mind reels from the shock.$",
    },

    ["blindfolded"] = {
        type         = "debuff",
        duration     = 300,
        initString_1 = "^Tethel gently ties a blindfold over your eyes.$",
        dropString_1 = "^Tethel removes your blindfold and helps you disembark.$",
    },

    ["haste (active)"] = {
        type         = "buff",
        duration     = 360,
        initString_1 = "^As you drink the tea, your muscles begin to quiver and twitch.$",
        dropString_1 = "^You feel less hasty.$",
    },

    ["haste (recovery)"] = {
        type         = "debuff",
        duration     = 1080,
        initString_1 = "^You feel less hasty.$",
        dropString_1 = "^Your muscles feel normal again.$",
    },
}

return M
