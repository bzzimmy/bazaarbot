package com.bazaarbot.bridge;

import com.bazaarbot.capture.PacketSerializer;
import com.bazaarbot.mixin.SignEditScreenAccessor;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import java.util.concurrent.CompletableFuture;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.inventory.AbstractSignEditScreen;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;

/** Primitive actions. Each runs on the client thread and resolves to a JSON result. */
final class BridgeCommands {
	private BridgeCommands() {
	}

	static CompletableFuture<JsonElement> handle(JsonObject req) {
		String op = req.has("op") ? req.get("op").getAsString() : "";
		Minecraft mc = Minecraft.getInstance();
		return mc.submit(() -> switch (op) {
			case "command" -> {
				// Leading slash is optional: "bz" and "/bz" both work.
				player(mc).connection.sendCommand(req.get("command").getAsString().replaceFirst("^/", ""));
				yield JsonNull.INSTANCE;
			}
			case "chat" -> {
				player(mc).connection.sendChat(req.get("message").getAsString());
				yield JsonNull.INSTANCE;
			}
			case "click" -> {
				LocalPlayer player = player(mc);
				int containerId = req.has("containerId") ? req.get("containerId").getAsInt() : player.containerMenu.containerId;
				int button = req.has("button") ? req.get("button").getAsInt() : 0;
				ContainerInput mode = req.has("mode") ? ContainerInput.valueOf(req.get("mode").getAsString()) : ContainerInput.PICKUP;
				mc.gameMode.handleContainerInput(containerId, req.get("slot").getAsInt(), button, mode, player);
				yield JsonNull.INSTANCE;
			}
			case "sign" -> {
				// Fill the open sign editor and close it; vanilla then sends the sign update itself.
				if (!(mc.gui.screen() instanceof AbstractSignEditScreen sign)) {
					throw new IllegalStateException("no sign editor open");
				}
				String[] messages = ((SignEditScreenAccessor) sign).bazaarbot$getMessages();
				JsonArray lines = req.getAsJsonArray("lines");
				for (int i = 0; i < messages.length; i++) {
					messages[i] = i < lines.size() ? lines.get(i).getAsString() : "";
				}
				sign.onClose();
				yield JsonNull.INSTANCE;
			}
			case "close" -> {
				player(mc).closeContainer();
				yield JsonNull.INSTANCE;
			}
			case "hotbar" -> {
				player(mc).getInventory().setSelectedSlot(req.get("slot").getAsInt());
				yield JsonNull.INSTANCE;
			}
			case "use" -> {
				mc.gameMode.useItem(player(mc), InteractionHand.MAIN_HAND);
				yield JsonNull.INSTANCE;
			}
			case "snapshot" -> snapshot(mc);
			default -> throw new IllegalArgumentException("unknown op: " + op);
		});
	}

	/** Current open container (if any) and player inventory, so a fresh client can sync without waiting for events. */
	private static JsonObject snapshot(Minecraft mc) {
		JsonObject out = new JsonObject();
		LocalPlayer player = mc.player;
		out.addProperty("inGame", player != null);
		if (player == null) {
			return out;
		}

		AbstractContainerMenu menu = player.containerMenu;
		if (menu != player.inventoryMenu) {
			JsonObject screen = new JsonObject();
			Screen current = mc.gui.screen();
			screen.addProperty("containerId", menu.containerId);
			screen.addProperty("menuType", String.valueOf(BuiltInRegistries.MENU.getKey(menu.getType())));
			screen.add("title", current == null ? JsonNull.INSTANCE : PacketSerializer.toJson(current.getTitle()));
			screen.add("items", PacketSerializer.toJson(menu.getItems()));
			out.add("screen", screen);
		} else {
			out.add("screen", JsonNull.INSTANCE);
		}
		out.addProperty("signOpen", mc.gui.screen() instanceof AbstractSignEditScreen);
		out.add("inventory", PacketSerializer.toJson(player.inventoryMenu.getItems()));
		out.addProperty("selectedSlot", player.getInventory().getSelectedSlot());
		return out;
	}

	private static LocalPlayer player(Minecraft mc) {
		if (mc.player == null || mc.getConnection() == null) {
			throw new IllegalStateException("not in game");
		}
		return mc.player;
	}
}
