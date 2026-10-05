package com.bazaarbot.capture;

import com.bazaarbot.bridge.BridgeServer;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicLong;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.network.protocol.BundlePacket;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.game.ClientboundSystemChatPacket;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Streams every captured packet as one JSON line to captures/capture-<timestamp>.jsonl.
 * Serialization happens on the calling (netty) thread so packets are recorded exactly as
 * they were at send/receive time; file IO happens on a background writer thread.
 */
public final class PacketCapture {
	private static final Logger LOGGER = LoggerFactory.getLogger("bazaarbot");
	private static final Gson GSON = new GsonBuilder()
		.disableHtmlEscaping()
		.serializeNulls()
		.serializeSpecialFloatingPointValues()
		.create();
	private static final String STOP = new String("<stop>");

	/** Packets kept in filtered mode: menus, signs, chat, sidebar, tab footer and connection state. */
	private static final Set<String> KEEP = Set.of(
		"clientbound/minecraft:open_screen",
		"clientbound/minecraft:container_set_content",
		"clientbound/minecraft:container_set_slot",
		"clientbound/minecraft:container_set_data",
		"clientbound/minecraft:container_close",
		"clientbound/minecraft:set_cursor_item",
		"clientbound/minecraft:open_sign_editor",
		"clientbound/minecraft:system_chat",
		"clientbound/minecraft:player_chat",
		"clientbound/minecraft:disguised_chat",
		"clientbound/minecraft:set_objective",
		"clientbound/minecraft:set_display_objective",
		"clientbound/minecraft:set_score",
		"clientbound/minecraft:reset_score",
		"clientbound/minecraft:set_player_team",
		"clientbound/minecraft:tab_list",
		"clientbound/minecraft:set_title_text",
		"clientbound/minecraft:set_subtitle_text",
		"clientbound/minecraft:login",
		"clientbound/minecraft:respawn",
		"clientbound/minecraft:start_configuration",
		"clientbound/minecraft:disconnect",
		"clientbound/minecraft:custom_payload",
		"serverbound/minecraft:chat",
		"serverbound/minecraft:chat_command",
		"serverbound/minecraft:chat_command_signed",
		"serverbound/minecraft:container_click",
		"serverbound/minecraft:container_button_click",
		"serverbound/minecraft:container_close",
		"serverbound/minecraft:sign_update",
		"serverbound/minecraft:use_item",
		"serverbound/minecraft:set_carried_item"
	);

	private static final BlockingQueue<String> queue = new LinkedBlockingQueue<>();
	private static final AtomicLong seq = new AtomicLong();
	/** What gets written to the capture file. The bridge always gets the filtered stream. */
	public enum Mode { OFF, FILTERED, ALL }

	private static volatile boolean running;
	private static volatile Mode mode = Mode.FILTERED;

	private PacketCapture() {
	}

	public static void start() {
		Path file = resolveCaptureDir().resolve("capture-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")) + ".jsonl");
		BufferedWriter writer;
		try {
			Files.createDirectories(file.getParent());
			writer = Files.newBufferedWriter(file, StandardCharsets.UTF_8);
		} catch (IOException e) {
			LOGGER.error("Could not open capture file {}, capture disabled", file, e);
			return;
		}

		Thread thread = new Thread(() -> writeLoop(writer), "bazaarbot-capture");
		thread.setDaemon(true);
		thread.start();
		running = true;

		Runtime.getRuntime().addShutdownHook(new Thread(() -> {
			running = false;
			queue.add(STOP);
			try {
				thread.join(2000);
			} catch (InterruptedException ignored) {
			}
		}, "bazaarbot-capture-shutdown"));

		LOGGER.info("Capturing packets to {}", file.toAbsolutePath());
	}

	/** Each packet is serialized once and fanned out to the capture file and the bridge. */
	public static void record(String dir, Packet<?> packet) {
		if (packet instanceof BundlePacket<?> bundle) {
			// Hypixel bundles menu and team updates together with entity spam, so filter per sub-packet.
			for (Packet<?> sub : bundle.subPackets()) {
				record(dir, sub);
			}
			return;
		}
		boolean wanted = KEEP.contains(packet.type().toString())
			&& !(packet instanceof ClientboundSystemChatPacket chat && chat.overlay()); // action bar spam
		boolean toFile = running && (mode == Mode.ALL || (mode == Mode.FILTERED && wanted));
		boolean toBridge = wanted && BridgeServer.hasClients();
		if (!toFile && !toBridge) {
			return;
		}

		JsonObject line = header(dir);
		try {
			line.addProperty("type", packet.type().toString());
			line.addProperty("class", packet.getClass().getSimpleName());
			line.add("data", new PacketSerializer().serializePacketBody(packet));
		} catch (Throwable t) {
			// Never let capture break the connection.
			line.addProperty("class", packet.getClass().getName());
			line.addProperty("error", t.toString());
		}
		String json = encode(line);
		if (json == null) {
			return;
		}
		if (toFile) {
			queue.add(json);
		}
		if (toBridge) {
			BridgeServer.broadcast(json);
		}
	}

	public static void setMode(Mode newMode) {
		mark("capture mode: " + newMode.name().toLowerCase());
		mode = newMode;
	}

	public static void mark(String text) {
		if (!running) {
			return;
		}
		JsonObject line = header("mark");
		line.add("text", new JsonPrimitive(text));
		String json = encode(line);
		if (json != null) {
			queue.add(json);
		}
	}

	private static JsonObject header(String dir) {
		JsonObject line = new JsonObject();
		line.addProperty("seq", seq.getAndIncrement());
		line.addProperty("t", System.currentTimeMillis());
		line.addProperty("dir", dir);
		return line;
	}

	private static String encode(JsonObject line) {
		try {
			return GSON.toJson(line);
		} catch (Throwable t) {
			LOGGER.warn("Failed to encode capture line", t);
			return null;
		}
	}

	private static void writeLoop(BufferedWriter writer) {
		try (writer) {
			while (true) {
				String line = queue.take();
				if (line == STOP) {
					break;
				}
				writer.write(line);
				writer.newLine();
				if (queue.isEmpty()) {
					writer.flush();
				}
			}
		} catch (IOException | InterruptedException e) {
			running = false;
			LOGGER.error("Capture writer stopped", e);
		}
	}

	/** -Dbazaarbot.captureDir wins, then the repo path baked in at build time, then <gameDir>/captures. */
	private static Path resolveCaptureDir() {
		String override = System.getProperty("bazaarbot.captureDir");
		if (override != null && !override.isBlank()) {
			return Path.of(override);
		}
		try (InputStream in = PacketCapture.class.getResourceAsStream("/bazaarbot.properties")) {
			if (in != null) {
				Properties props = new Properties();
				props.load(in);
				String baked = props.getProperty("captureDir");
				if (baked != null && !baked.isBlank() && !baked.contains("${")) {
					return Path.of(baked);
				}
			}
		} catch (IOException ignored) {
		}
		return FabricLoader.getInstance().getGameDir().resolve("captures");
	}
}
