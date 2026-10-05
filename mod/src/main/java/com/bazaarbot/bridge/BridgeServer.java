package com.bazaarbot.bridge;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.ChannelInitializer;
import io.netty.channel.MultiThreadIoEventLoopGroup;
import io.netty.channel.SimpleChannelInboundHandler;
import io.netty.channel.group.ChannelGroup;
import io.netty.channel.group.DefaultChannelGroup;
import io.netty.channel.nio.NioIoHandler;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;
import io.netty.handler.codec.http.HttpObjectAggregator;
import io.netty.handler.codec.http.HttpServerCodec;
import io.netty.handler.codec.http.websocketx.TextWebSocketFrame;
import io.netty.handler.codec.http.websocketx.WebSocketServerProtocolHandler;
import io.netty.util.concurrent.DefaultThreadFactory;
import io.netty.util.concurrent.GlobalEventExecutor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Local WebSocket server (127.0.0.1 only). Clients receive every filtered packet event as a
 * JSON text frame and can send requests: {"id": 1, "op": "click", ...}. Each request gets one
 * response: {"id": 1, "ok": true, "result": ...} or {"id": 1, "ok": false, "error": "..."}.
 * Events carry "seq" and responses carry "id", so clients can tell them apart.
 */
public final class BridgeServer {
	private static final Logger LOGGER = LoggerFactory.getLogger("bazaarbot");
	private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
	private static final ChannelGroup clients = new DefaultChannelGroup(GlobalEventExecutor.INSTANCE);

	private BridgeServer() {
	}

	public static void start(int port) {
		var group = new MultiThreadIoEventLoopGroup(1, new DefaultThreadFactory("bazaarbot-bridge", true), NioIoHandler.newFactory());
		new ServerBootstrap()
			.group(group)
			.channel(NioServerSocketChannel.class)
			.childHandler(new ChannelInitializer<SocketChannel>() {
				@Override
				protected void initChannel(SocketChannel ch) {
					ch.pipeline().addLast(
						new HttpServerCodec(),
						new HttpObjectAggregator(1 << 16),
						new WebSocketServerProtocolHandler("/", null, false, 1 << 20),
						new FrameHandler());
				}
			})
			.bind("127.0.0.1", port)
			.addListener(future -> {
				if (future.isSuccess()) {
					LOGGER.info("Bridge listening on ws://127.0.0.1:{}", port);
				} else {
					LOGGER.error("Bridge failed to bind port {}", port, future.cause());
				}
			});
	}

	public static boolean hasClients() {
		return !clients.isEmpty();
	}

	public static void broadcast(String json) {
		clients.writeAndFlush(new TextWebSocketFrame(json));
	}

	private static final class FrameHandler extends SimpleChannelInboundHandler<TextWebSocketFrame> {
		@Override
		public void userEventTriggered(ChannelHandlerContext ctx, Object evt) throws Exception {
			// Only stream events once the handshake is done; closed channels leave the group automatically.
			if (evt instanceof WebSocketServerProtocolHandler.HandshakeComplete) {
				clients.add(ctx.channel());
				LOGGER.info("Bridge client connected from {}", ctx.channel().remoteAddress());
			}
			super.userEventTriggered(ctx, evt);
		}

		@Override
		protected void channelRead0(ChannelHandlerContext ctx, TextWebSocketFrame frame) {
			JsonObject request;
			try {
				request = JsonParser.parseString(frame.text()).getAsJsonObject();
			} catch (RuntimeException e) {
				reply(ctx, null, null, "bad request: " + e.getMessage());
				return;
			}
			JsonElement id = request.get("id");
			BridgeCommands.handle(request).whenComplete((result, error) -> {
				Throwable cause = error != null && error.getCause() != null ? error.getCause() : error;
				reply(ctx, id, result, cause == null ? null : String.valueOf(cause.getMessage() != null ? cause.getMessage() : cause));
			});
		}

		private static void reply(ChannelHandlerContext ctx, JsonElement id, JsonElement result, String error) {
			JsonObject response = new JsonObject();
			response.add("id", id);
			response.addProperty("ok", error == null);
			if (error == null) {
				response.add("result", result);
			} else {
				response.addProperty("error", error);
			}
			ctx.writeAndFlush(new TextWebSocketFrame(GSON.toJson(response)));
		}
	}
}
