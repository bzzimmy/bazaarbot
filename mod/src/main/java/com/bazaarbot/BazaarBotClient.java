package com.bazaarbot;

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

			// /bbcapture all|filtered switches between dumping every packet and only the useful ones.
			dispatcher.register(ClientCommands.literal("bbcapture")
				.then(ClientCommands.literal("all").executes(ctx -> {
					PacketCapture.setCaptureAll(true);
					ctx.getSource().sendFeedback(Component.literal("[bazaarbot] capturing all packets"));
					return 1;
				}))
				.then(ClientCommands.literal("filtered").executes(ctx -> {
					PacketCapture.setCaptureAll(false);
					ctx.getSource().sendFeedback(Component.literal("[bazaarbot] capturing filtered packets"));
					return 1;
				})));
		});
	}
}
