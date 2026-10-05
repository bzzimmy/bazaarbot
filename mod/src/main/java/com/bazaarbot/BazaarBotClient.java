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

		// /bbmark <text> writes a label into the capture so sessions are easy to navigate.
		ClientCommandRegistrationCallback.EVENT.register((dispatcher, buildContext) -> dispatcher.register(
			ClientCommands.literal("bbmark")
				.then(ClientCommands.argument("text", StringArgumentType.greedyString())
					.executes(ctx -> {
						String text = StringArgumentType.getString(ctx, "text");
						PacketCapture.mark(text);
						ctx.getSource().sendFeedback(Component.literal("[bazaarbot] marked: " + text));
						return 1;
					}))
		));
	}
}
