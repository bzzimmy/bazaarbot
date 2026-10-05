package com.bazaarbot;

import com.bazaarbot.bridge.BridgeServer;
import com.bazaarbot.capture.PacketCapture;
import com.mojang.brigadier.arguments.StringArgumentType;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.command.v2.ClientCommandRegistrationCallback;
import net.fabricmc.fabric.api.client.command.v2.ClientCommands;
import net.minecraft.network.chat.Component;

public class BazaarBotClient implements ClientModInitializer {
	@Override
	public void onInitializeClient() {
		PacketCapture.start();
		BridgeServer.start(Integer.getInteger("bazaarbot.bridgePort", 7777));

		ClientCommandRegistrationCallback.EVENT.register((dispatcher, buildContext) -> {
			// /bbmark <text> writes a label into the capture so sessions are easy to navigate.
			dispatcher.register(ClientCommands.literal("bbmark")
				.then(ClientCommands.argument("text", StringArgumentType.greedyString())
					.executes(ctx -> {
						String text = StringArgumentType.getString(ctx, "text");
						PacketCapture.mark(text);
						ctx.getSource().sendFeedback(Component.literal("[bazaarbot] marked: " + text));
						return 1;
					})));

			// /bbcapture off|filtered|all controls what is written to the capture file.
			var capture = ClientCommands.literal("bbcapture");
			for (PacketCapture.Mode mode : PacketCapture.Mode.values()) {
				String name = mode.name().toLowerCase();
				capture.then(ClientCommands.literal(name).executes(ctx -> {
					PacketCapture.setMode(mode);
					ctx.getSource().sendFeedback(Component.literal("[bazaarbot] capture: " + name));
					return 1;
				}));
			}
			dispatcher.register(capture);
		});
	}
}
