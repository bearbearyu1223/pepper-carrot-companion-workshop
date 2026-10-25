-- Episode 6 "The Potion Contest" for Lesson 4's walkthrough demos (E, F, G): 1 episode, its 9 pages,
-- all 31 characters, and the 28 page_characters rows that link them. A subset of the finished app's data.
-- Load after alembic upgrade head; see README.md. Comic content: David Revoy, Pepper & Carrot, CC BY 4.0.
BEGIN;

INSERT INTO public.episodes (id, slug, title, episode_number, language, cover_image_url, plot_summary, credits_url, published_at, ingested_at) VALUES ('58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 'ep06-the-potion-contest', 'Episode 6: The Potion Contest', 6, 'en', 'episodes/ep06-the-potion-contest/cover-display.webp', 'Pepper wakes up to find herself sailing through the clouds aboard her enchanted bed, brought by Carrot to the Komona Potion Contest despite falling asleep. The contest quickly descends into chaos as Saffron''s dangerous potion transforms a canary into a giant monster that threatens Komona. In a final act of bravery, Pepper uses a sample of Carrot''s pee from his last vet visit, declaring it a potion, and successfully scares the giant bird away, saving the town and winning the contest in a surprising twist.', 'https://www.peppercarrot.com/en/webcomic/ep06_The-Potion-Contest.html', '2015-03-28 00:00:00+00', '2026-05-02 21:57:28.673704+00');


INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('a006ee31-0558-4c53-8764-07b1512755df', 'Pepper', '{}', 'A young witch of the Chaosah school of chaos magic. Protagonist.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('315aad79-38db-45eb-b645-bcff26f1cf57', 'Carrot', '{"the cat"}', 'Pepper''s mischievous orange tabby cat and constant companion.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('97c1f472-10d3-41b3-97f5-3591d17687da', 'Thyme', '{}', 'The small and wise leader of the Chaosah witches — calculating and sneaky.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('23775d94-85f4-4880-92e0-00b10e1c5597', 'Cayenne', '{}', 'The tall, thin and rigid witch of Chaosah. Spell teacher for Pepper.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('57483ec4-3887-423a-9ac4-a0d6dd2ae41c', 'Cumin', '{}', 'A bon-vivant witch of Chaosah. Teacher of potions and potion ingredients for Pepper.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('1bc649e2-1450-4050-8b1e-21958bdb00f6', 'Saffron', '{}', 'A young witch and frequent rival to Pepper across school competitions.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('a947dfc6-ae9d-43fe-8b63-a94cc13aa88f', 'Shichimi', '{}', 'A young witch from the Ah school of magic — one of Pepper''s friends.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('c8612a49-35a1-4925-9ec1-4954f12d7e5d', 'Coriander', '{}', 'A young witch of Zombiah — granddaughter of Apiaceae and friend in Pepper''s circle.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('0887f79a-88f4-447e-86b6-e1dbfdf26258', 'Camomile', '{}', 'A young witch from Pepper''s class at the School of Hippiah Witchcraft.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('af217e1b-8e92-4ac4-be26-168a52a5de00', 'Torreya', '{}', 'Pilot of the dragon Arra.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('3b0f75e8-9615-4604-8c72-694523313609', 'Truffel', '{"Saffron''s cat"}', 'A female white angora cat — Saffron''s familiar.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('a3797553-17dd-4d91-8857-15bccee94b6b', 'Yuzu', '{"Shichimi''s familiar",kitsune}', 'A two-tailed orange fox (kitsune) that travels beside Shichimi.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('fc94832c-5ef1-4c56-ac13-52a3006fa127', 'Mango', '{"Coriander''s familiar"}', 'A black cockerel that is often seen with Coriander.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('97d46718-962a-4c5f-b76b-77c9c72141e3', 'Durian', '{"Spirulina''s fish"}', 'A red male betta splendens fish — Spirulina''s familiar.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('9a1a54e2-cc6e-46ca-b960-6a9a1dfe8475', 'Squeak', '{"Camomile''s familiar"}', 'A squirrel that lives under Camomile''s hat.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('ac310907-0028-441c-b241-0ea0b24ce35a', 'Spirulina', '{}', 'The mysterious witch-representative of Aquah.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('9bedd162-6a9f-4d8f-9d5b-0fc7a46fb51a', 'Vanilla', '{"Diva Capsica"}', 'Master of Magmah, also known as Diva Capsica — passionate, theatrical, dreams of staging the most impressive fire show.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('adb33472-f01b-4178-a12a-b49fe11c6f05', 'The First Mermaid', '{}', 'Master of Aquah — a giant mermaid with a gold trident; possibly mythical.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('66962d89-f2c0-478c-8f47-ff33d69fcc8d', 'Apiaceae', '{}', 'Founder of the Zombiah school and Queen of Qualicity. Coriander''s grandmother and Soumbala''s creator.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('4f36afdb-3010-421f-8815-bde12b16a406', 'Soumbala', '{}', 'Master of Zombiah — a robotic creation of Apiaceae''s that holds her wisdom.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('0b4c1151-a0b6-4449-99d8-736d58fe1553', 'Botanic', '{}', 'Former Master of Hippiah, specialised in herbal medicine.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('b01240ee-fbbf-43d5-bdb9-40b8314400dd', 'Basilic', '{}', 'Current Master of Hippiah — apprentice of Botanic, brilliant and a little arrogant.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('8e1f4e62-16fd-4413-bbd5-15e387a5a93c', 'Quassia', '{}', 'Teacher of Hippiah.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('9a5e3393-0f39-4642-a48b-71b0c040d4d8', 'Millet', '{}', 'Beloved former teacher of Hippiah.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('562b278d-eec6-4f36-85b9-39fd709c02d5', 'Brasic', '{}', 'A human swordsman who hunts treasure alongside Vinya and Frostir.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('d46ee8b5-41eb-4ea6-af15-c0432aac9238', 'Vinya', '{}', 'A ranged adventurer wielding a bow.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('be03a7f0-e4f1-4d95-a62d-517457cced80', 'Frostir', '{}', 'An adventurer who travels with Brasic and Vinya.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('b8be0bb7-b80d-42eb-be0c-13c316cf11ee', 'Mayor of Komona', '{}', 'The current mayor of Komona City.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('25b48cca-4508-48fd-8e68-81ed72ab8073', 'Prince Acren', '{}', 'The uncrowned prince of Acren — orphaned after his parents'' death.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('9a7871a7-8e3e-433a-a800-07e5d0b3b1a5', 'The Sage', '{}', 'The mysterious and wise teacher of Hereva.', NULL, NULL);
INSERT INTO public.characters (id, name, aliases, bio, first_appearance_episode_id, image_url) VALUES ('44dcd70c-e1ac-40c0-a1bb-9246dd1f2643', 'Fairies', '{}', 'Magical winged creatures that inhabit the world of Hereva.', NULL, NULL);


INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('4cc69212-1cb1-4066-9871-b6b29490a194', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 2, 'episodes/ep06-the-potion-contest/pages/002-display.webp', 'episodes/ep06-the-potion-contest/pages/002-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/002-original.jpg', 'Pepper: !!!
Pepper: Carrot! You''re so cute to have thought of bringing me to the Contest!
Pepper: Fan-tas-tic!
Pepper: You even thought of bringing a potion, my clothes, and my hat...
Pepper: ...let''s see which potion you brought...', 'The wide shot pulls back to reveal the brilliant absurdity of Pepper''s situation: her wooden bed is dangling from ropes lashed to her broom, and Carrot, perched proudly atop the broom-handle in tiny aviator goggles, is steering the whole rig through the clouds while a little orange dragonet flits alongside. Pepper, half-buried in blankets, gawks up at her cat in disbelief. Once she puts the picture together her face melts into delighted relief — her clever Carrot has even thought to bring her to the contest, along with a bottled potion, her clothes, and her hat. Standing now on the swaying bed in full witch regalia, she beams down at the city below and asks to see which potion he packed for her.', '{whimsical,hopeful,comedic}', '{"width": 2481, "height": 3503, "blurhash": "KaQSSKi^%#?wW?jZyEt7s:", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('f8eed4a0-4336-4589-9f3c-6f0796c8d18f', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 3, 'episodes/ep06-the-potion-contest/pages/003-display.webp', 'episodes/ep06-the-potion-contest/pages/003-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/003-original.jpg', 'Pepper: WHAT?!!
Mayor of Komona: As Mayor of Komona, I declare the potion contest... Open!
Mayor of Komona: Our town is delighted to welcome no fewer than four witches for this first edition.
Mayor of Komona: Please give a huge round of applause:
Komona Potion Contest', 'A jagged blue panel of Pepper''s horror-stricken face announces that whatever Carrot grabbed is very much not a potion — and her dismay rings out across the sky as she screams a single ''WHAT?!!'' that echoes over the rooftops of Komona. Down below, the Grand Plaza is packed under a banner that reads Komona Potion Contest, the round little Mayor of Komona at the podium throwing his arms wide and declaring the contest open. He brags that the town is delighted to welcome no fewer than four witches for this first edition and asks the crowd for a huge round of applause. The mood pivots cleanly from cosmic disaster in the air to civic pomp on the ground.', '{alarmed,ceremonial,anticipatory}', '{"width": 2481, "height": 3503, "blurhash": "KKNdEtyFx_pyxDxY5aM{xD", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('2d9978ce-8fa9-47d1-b88a-003e3247fb77', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 7, 'episodes/ep06-the-potion-contest/pages/007-display.webp', 'episodes/ep06-the-potion-contest/pages/007-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/007-original.jpg', 'CAW-CAW-Caaaaaaaa~~
BAM!
Mayor of Komona: Run, idiot! The competition is over! ...save yourself!
Pepper: ...huh, cool! So it''s my turn now?
Pepper: ...my potion will at least be worth a few laughs because...', 'The posh canary explodes upward into a colossal monster, towering over Komona''s rooftops with a deafening ''CAW-CAW-Caaaaaaaa'' as buildings crack and crumble beneath its enormous talons. A thunderous BAM rattles the plaza as one giant claw smashes down. Amid the chaos, the Mayor — half hidden under his hat — bellows at Pepper to run, idiot, the competition is over, save yourself. Pepper, perfectly serene, cheerfully replies that since it''s her turn now, her potion will at least be worth a few laughs.', '{chaotic,action,comedic}', '{"width": 2481, "height": 3503, "blurhash": "KWO38zo$yFkNM}M{_Mt7nj", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('7a2c6beb-30e5-4822-bacb-9f9ec0a78245', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 5, 'episodes/ep06-the-potion-contest/pages/005-display.webp', 'episodes/ep06-the-potion-contest/pages/005-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/005-original.jpg', 'Mayor of Komona: FANTASTIC! Coriander defies death itself with this mi-ra-cu-lous potion!
Clap Clap Clap Clap Clap Clap
Saffron: ...but please, save your applause, people of Komona!
Saffron: Because here is MY Potion!
Saffron: The real potion you''ve all been waiting for: the one which will amaze your neighbors...
Saffron: ...make them jealous!
Saffron: ...all this is possible with the simple application of a single drop of my...
Saffron: ...Potion of POSHNESS!
Clap Clap Clap Clap Clap Clap Clap Clap
Mayor of Komona: Fantastic! Incredible! This potion could make all of Komona rich!
Saffron: Your applause can''t be wrong. Coriander has already been eliminated.', 'The Mayor gushes that Coriander defies death itself with her miraculous potion as the crowd thunders applause, but Saffron sweeps in mid-ovation and tells Komona to save its claps because here is HER potion — the real one everyone''s been waiting for, guaranteed to amaze your neighbors and make them jealous. With one theatrical drop of her Potion of Poshness, Saffron transforms the zombie canary into a preening, jewelry-draped, curly-coiffed aristocrat-bird that struts the stage to even louder cheers. The Mayor cries out that this potion could make all of Komona rich, and Saffron smugly assures Coriander her applause can''t be wrong — she''s already been eliminated.', '{showy,rivalrous,smug}', '{"width": 2481, "height": 3503, "blurhash": "KPOy-7-qpeT2e.n#0-yCel", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 6, 'episodes/ep06-the-potion-contest/pages/006-display.webp', 'episodes/ep06-the-potion-contest/pages/006-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/006-original.jpg', 'Saffron: That last demonstration would now seem difficult to beat for Shichimi!
Shichimi: I... I did not know we had to give a demonstration.
Mayor of Komona: ...come on Shichimi, everyone''s waiting for you.
Shichimi: NO! I cannot, it is too dangerous SORRY!
Mayor of Komona: It seems, Ladies & Gentlemen that Shichimi forfeits...
Saffron: Give me that!
Saffron: ...and stop pretending to be shy, you''re spoiling the show.
Saffron: Everyone already knows that I''ve won the contest no matter what your potion does...
!!!
Shichimi: CAREFUL!!! It''s a potion for GIANT MONSTERS!
BZZZIIIO!', 'Saffron crows that her demonstration will now be hard for Shichimi to beat, but Shichimi clutches her own flask nervously and admits she didn''t even know they had to demonstrate, then refuses outright when called up because her potion is too dangerous. The Mayor announces that Shichimi forfeits — and Saffron impatiently snatches the flask from her hands, telling her to stop pretending to be shy and spoil the show, declaring that she''s already won regardless of what anyone else does. Pepper and Carrot watch with growing horror as Saffron pours Shichimi''s flask onto the posh canary; Shichimi finally finds her voice and shouts a warning that it''s a potion for giant monsters, just as the bird is engulfed in a crackling green BZZZIIIO of light and starts to grow.', '{tense,rivalrous,alarmed}', '{"width": 2481, "height": 3503, "blurhash": "KVODj{kWwM}BkWXlL2X9WY", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('5d4c8a87-ca1f-4977-bd3a-c591e985b853', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 1, 'episodes/ep06-the-potion-contest/pages/001-display.webp', 'episodes/ep06-the-potion-contest/pages/001-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/001-original.jpg', 'Pepper: Oh shoot, I fell asleep with the window open, again...
Pepper: ...it''s so windy...
Pepper: ...and why can I see Komona through the window?
Pepper: KOMONA!
Pepper: The Potion Contest!
Pepper: I must''ve... must''ve accidentally fallen asleep!
Pepper: ...but?
Pepper: Where am I ?!?
Quack?', 'Pepper drowses in bed beneath a swirl of her own hair as the wind tugs at her, idly grumbling that she''s left the window open again — until she realises the wind is real and that she can see the floating tree-city of Komona drifting past her window. Her bed is in fact sailing through the open sky on a great cushion of clouds. She bolts upright in alarm, hands to her cheeks, screaming the name of the city as the dread of the Potion Contest hits her and she yelps that she must have accidentally fallen asleep. Looking over the edge of the bedclothes, she finds a small orange dragonet smiling expectantly at her — and asks, dazed, just where on earth she is.', '{dreamy,alarmed,comedic}', '{"width": 2481, "height": 3503, "blurhash": "KOPPGmn%k@%#xtW=_ND%Mx", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 4, 'episodes/ep06-the-potion-contest/pages/004-display.webp', 'episodes/ep06-the-potion-contest/pages/004-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/004-original.jpg', 'Mayor of Komona: All the way from the great Technologist''s Union, it''s an honor to welcome the ravishing and ingenious Coriander!
Mayor of Komona: ...not to forget our local girl, Komona''s very own witch Saffron!
Mayor of Komona: ...Our third participant comes to us from the lands of the setting moons, Shichimi!
Mayor of Komona: ...and finally, our last participant, from the forest of Squirrel''s End, Pepper!
Mayor of Komona: Let the games begin!
Mayor of Komona: The vote will be by applaud-o-meter.
Mayor of Komona: First up, Coriander''s demonstration
Coriander: Ladies & Gentlemen...
Coriander: ...fear death no more, thanks to my...
Coriander: ...Potion of ZOMBIFICATION!
Clap Clap Clap Clap Clap Clap Clap Clap', 'The Mayor introduces the four contestants in a row of portrait panels: first Coriander, a poised brown-skinned witch from the great Technologist''s Union with a small dragonet on her shoulder; then Komona''s own redheaded local, Saffron, smiling smugly with her cat; then the soft-spoken blonde Shichimi from the lands of the setting moons cradling a flask and a small fox-creature; and finally a flustered Pepper from the forest of Squirrel''s End, gripping a glowing yellow flask with Carrot''s face peering out the top. The Mayor declares the games begun and explains the vote will be tallied by an applaud-o-meter. Coriander goes first, presenting a flask with theatrical flair as she announces the Potion of Zombification — and dribbles it onto a roasted bird, which springs back to life as a yellow undead canary while the crowd erupts in claps.', '{ceremonial,rivalrous,showy}', '{"width": 2481, "height": 3503, "blurhash": "KBOMsaQ:G0~XTdxB-qv#It", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('cf1e7f74-ec9a-4a22-863e-4bcf6998ade5', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 8, 'episodes/ep06-the-potion-contest/pages/008-display.webp', 'episodes/ep06-the-potion-contest/pages/008-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/008-original.jpg', 'Pepper: There you go...
Pepper: ...as usual, everyone leaves just when it''s our turn.
Pepper: At least I have an idea of what we''ll be able to do with your "potion", Carrot.
Pepper: ...put everything back in order here and head home!
Pepper: HEY!
Pepper: You Oversized-posh-zombie-canary!
CRACK!
Pepper: Wanna try one last potion? ...
...not really, huh?', 'Pepper plants her boots in the empty cracked plaza, broom over her shoulder and Carrot at her ankles, sighing that as usual everyone leaves just when it''s their turn — but adding that she has an idea of what to do with Carrot''s ''potion'' before they put everything back in order and head home. She kicks off on her broom with Carrot tucked behind her and shouts up at the giant canary, calling it an oversized-posh-zombie-canary, then snatches a stone tower-cap with a CRACK as she swoops past the bird''s beak. Hovering eye-to-eye with the monster she dangles her flask and offers, sweetly, one last potion to try — and the canary, eyes wide and panicking, grunts back that... not really, huh.', '{determined,cheeky,action}', '{"width": 2481, "height": 3503, "blurhash": "KJNv;.%1Y7T1ofeS?^xBt6", "dominant_color": "#FFFFFF"}');
INSERT INTO public.pages (id, episode_id, page_number, image_url, thumbnail_url, original_url, ocr_text, visual_description, mood_tags, image_metadata) VALUES ('63c83b88-487e-4214-8742-d1552153262b', '58dcdcba-c7ca-4d40-8f21-ef968dfb7d3b', 9, 'episodes/ep06-the-potion-contest/pages/009-display.webp', 'episodes/ep06-the-potion-contest/pages/009-thumbnail.webp', 'episodes/ep06-the-potion-contest/pages/009-original.jpg', 'Pepper: Yeah, read the label, carefully...
Pepper: ...I won''t think twice before pouring it all over you if you don''t get out of Komona right away!
Mayor of Komona: Because she saved our town when it was in peril, we award first place to Pepper for her Potion of ... ??!!
Pepper: ... Haha! yep ...
Pepper: ... huh... in fact, it''s not really a potion ; it''s my cat''s pee sample from his last trip to the vet!
Mayor of Komona: ... no demo then ?...', 'Pepper holds up the small yellow flask to the giant canary with a wicked grin, telling it to read the label carefully, threatening to pour the whole thing all over it if it doesn''t get out of Komona right away. The terrified bird wheels around and flees, dwindling into a yellow speck across the rooftops as Pepper and Carrot watch from their broom with quiet smiles. In the final panel, confetti showers the plaza as the Mayor crowns Pepper with a sash and a heavy bag of fifty thousand Ko, declaring that because she saved their town when it was in peril, first place is awarded to Pepper for her Potion of — and trails off bewildered. Pepper laughs and admits, with a grin, that it''s not really a potion at all but a sample of her cat''s pee from his last trip to the vet — leaving the Mayor stammering ''no demo then?'' while a fuming Saffron and Coriander look on in the background.', '{triumphant,comedic,cheeky}', '{"width": 2481, "height": 3503, "blurhash": "KNO:d~rq.T%eSORjr{NFkS", "dominant_color": "#FFFFFF"}');


INSERT INTO public.page_characters (page_id, character_id) VALUES ('5d4c8a87-ca1f-4977-bd3a-c591e985b853', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('4cc69212-1cb1-4066-9871-b6b29490a194', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('4cc69212-1cb1-4066-9871-b6b29490a194', '315aad79-38db-45eb-b645-bcff26f1cf57');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('f8eed4a0-4336-4589-9f3c-6f0796c8d18f', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('f8eed4a0-4336-4589-9f3c-6f0796c8d18f', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', '315aad79-38db-45eb-b645-bcff26f1cf57');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', '1bc649e2-1450-4050-8b1e-21958bdb00f6');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', 'a947dfc6-ae9d-43fe-8b63-a94cc13aa88f');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', 'c8612a49-35a1-4925-9ec1-4954f12d7e5d');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('29100226-94de-47b3-b2c2-2766db4898b2', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('7a2c6beb-30e5-4822-bacb-9f9ec0a78245', '1bc649e2-1450-4050-8b1e-21958bdb00f6');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('7a2c6beb-30e5-4822-bacb-9f9ec0a78245', 'c8612a49-35a1-4925-9ec1-4954f12d7e5d');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('7a2c6beb-30e5-4822-bacb-9f9ec0a78245', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', '315aad79-38db-45eb-b645-bcff26f1cf57');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', '1bc649e2-1450-4050-8b1e-21958bdb00f6');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', 'a947dfc6-ae9d-43fe-8b63-a94cc13aa88f');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('d850cf2c-f829-43fb-aa11-e3fa4873b819', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('2d9978ce-8fa9-47d1-b88a-003e3247fb77', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('2d9978ce-8fa9-47d1-b88a-003e3247fb77', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('cf1e7f74-ec9a-4a22-863e-4bcf6998ade5', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('cf1e7f74-ec9a-4a22-863e-4bcf6998ade5', '315aad79-38db-45eb-b645-bcff26f1cf57');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('63c83b88-487e-4214-8742-d1552153262b', 'a006ee31-0558-4c53-8764-07b1512755df');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('63c83b88-487e-4214-8742-d1552153262b', '315aad79-38db-45eb-b645-bcff26f1cf57');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('63c83b88-487e-4214-8742-d1552153262b', '1bc649e2-1450-4050-8b1e-21958bdb00f6');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('63c83b88-487e-4214-8742-d1552153262b', 'c8612a49-35a1-4925-9ec1-4954f12d7e5d');
INSERT INTO public.page_characters (page_id, character_id) VALUES ('63c83b88-487e-4214-8742-d1552153262b', 'b8be0bb7-b80d-42eb-be0c-13c316cf11ee');

COMMIT;
