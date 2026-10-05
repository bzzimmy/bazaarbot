package com.bazaarbot.mixin;

import com.bazaarbot.capture.PacketCapture;
import io.netty.channel.ChannelFutureListener;
import io.netty.channel.ChannelHandlerContext;
import net.minecraft.network.Connection;
import net.minecraft.network.protocol.Packet;
import net.minecraft.network.protocol.PacketFlow;
import org.jspecify.annotations.Nullable;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Every decoded inbound packet passes through channelRead0, and every outbound packet
 * ends up in doSendPacket. Only the client side of a connection is captured, so the
 * integrated server's connection in singleplayer is ignored.
 */
@Mixin(Connection.class)
public abstract class ConnectionMixin {
	@Inject(method = "channelRead0", at = @At("HEAD"))
	private void bazaarbot$onReceive(ChannelHandlerContext ctx, Packet<?> packet, CallbackInfo ci) {
		if (((Connection) (Object) this).getReceiving() == PacketFlow.CLIENTBOUND) {
			PacketCapture.record("in", packet);
		}
	}

	@Inject(method = "doSendPacket", at = @At("HEAD"))
	private void bazaarbot$onSend(Packet<?> packet, @Nullable ChannelFutureListener listener, boolean flush, CallbackInfo ci) {
		if (((Connection) (Object) this).getSending() == PacketFlow.SERVERBOUND) {
			PacketCapture.record("out", packet);
		}
	}
}
