package com.bazaarbot.capture;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.mojang.serialization.DynamicOps;
import com.mojang.serialization.JsonOps;
import io.netty.buffer.ByteBuf;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalDouble;
import java.util.OptionalInt;
import java.util.OptionalLong;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.core.Holder;
import net.minecraft.core.RegistryAccess;
import net.minecraft.core.component.DataComponentType;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.Tag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.ComponentSerialization;
import net.minecraft.network.protocol.Packet;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.RegistryOps;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.component.ItemLore;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.StateHolder;
import net.minecraft.world.level.material.Fluid;

/**
 * Turns an arbitrary packet into JSON by walking its fields reflectively. Types we care
 * about (items, text components, registry references) get readable special cases;
 * everything else falls back to its fields or toString(). Large primitive arrays such as
 * chunk data are summarized instead of dumped.
 */
final class PacketSerializer {
	private static final int MAX_DEPTH = 24;
	private static final int MAX_ELEMENTS = 4096;
	private static final int MAX_INLINE_ARRAY = 64;
	private static final int MAX_NODES = 50_000;
	private static final Map<Class<?>, List<Field>> FIELD_CACHE = new ConcurrentHashMap<>();

	private static RegistryAccess cachedRegistries;
	private static DynamicOps<JsonElement> cachedOps = JsonOps.INSTANCE;

	private final Set<Object> stack = Collections.newSetFromMap(new IdentityHashMap<>());
	private final DynamicOps<JsonElement> ops = ops();
	private int nodes;

	JsonElement serializePacketBody(Packet<?> packet) {
		return fields(packet, 0);
	}

	private JsonElement value(Object o, int depth) {
		if (o == null) {
			return JsonNull.INSTANCE;
		}
		if (++nodes > MAX_NODES) {
			return new JsonPrimitive("<truncated>");
		}
		if (depth > MAX_DEPTH) {
			return new JsonPrimitive("<max depth> " + safeToString(o));
		}

		if (o instanceof String s) return new JsonPrimitive(s);
		if (o instanceof Number n) return new JsonPrimitive(n);
		if (o instanceof Boolean b) return new JsonPrimitive(b);
		if (o instanceof Character c) return new JsonPrimitive(c);
		if (o instanceof Enum<?> e) return new JsonPrimitive(e.name());
		if (o instanceof UUID || o instanceof Identifier || o instanceof ResourceKey<?> || o instanceof Tag) {
			return new JsonPrimitive(o.toString());
		}
		// Game objects link into huge shared graphs (a BlockState reaches every other state), so print them as ids.
		if (o instanceof StateHolder<?, ?>) return new JsonPrimitive(o.toString());
		if (o instanceof Block b) return registryId(BuiltInRegistries.BLOCK.getKey(b), o);
		if (o instanceof Item i) return registryId(BuiltInRegistries.ITEM.getKey(i), o);
		if (o instanceof Fluid f) return registryId(BuiltInRegistries.FLUID.getKey(f), o);
		if (o instanceof EntityType<?> e) return registryId(BuiltInRegistries.ENTITY_TYPE.getKey(e), o);
		if (o instanceof BlockEntityType<?> e) return registryId(BuiltInRegistries.BLOCK_ENTITY_TYPE.getKey(e), o);
		if (o instanceof MenuType<?> m) return registryId(BuiltInRegistries.MENU.getKey(m), o);
		if (o instanceof DataComponentType<?> t) return registryId(BuiltInRegistries.DATA_COMPONENT_TYPE.getKey(t), o);
		if (o instanceof Component c) return component(c);
		if (o instanceof ItemStack stack) return item(stack);
		if (o instanceof Holder<?> holder) {
			Optional<? extends ResourceKey<?>> key = holder.unwrapKey();
			return key.isPresent() ? new JsonPrimitive(key.get().identifier().toString()) : value(holder.value(), depth + 1);
		}
		if (o instanceof Optional<?> opt) return opt.isPresent() ? value(opt.get(), depth + 1) : JsonNull.INSTANCE;
		if (o instanceof OptionalInt opt) return opt.isPresent() ? new JsonPrimitive(opt.getAsInt()) : JsonNull.INSTANCE;
		if (o instanceof OptionalLong opt) return opt.isPresent() ? new JsonPrimitive(opt.getAsLong()) : JsonNull.INSTANCE;
		if (o instanceof OptionalDouble opt) return opt.isPresent() ? new JsonPrimitive(opt.getAsDouble()) : JsonNull.INSTANCE;
		if (o instanceof ByteBuf buf) return summary("ByteBuf", buf.readableBytes());
		if (o instanceof Packet<?> packet && depth > 0) {
			// Bundled sub-packets keep their protocol type so they read like top-level packets.
			JsonObject obj = new JsonObject();
			obj.addProperty("type", packet.type().toString());
			obj.addProperty("class", packet.getClass().getSimpleName());
			obj.add("data", guarded(packet, depth, () -> fields(packet, depth + 1)));
			return obj;
		}

		Class<?> cls = o.getClass();
		if (cls.isArray()) return array(o, depth);
		if (o instanceof Map<?, ?> map) return guarded(o, depth, () -> map(map, depth));
		if (o instanceof Iterable<?> it) return guarded(o, depth, () -> iterable(it, depth));
		if (cls.isSynthetic() || cls.isHidden()) return new JsonPrimitive("<lambda>");
		if (isOpaque(cls)) return new JsonPrimitive(safeToString(o));

		return guarded(o, depth, () -> fields(o, depth + 1));
	}

	private JsonElement guarded(Object o, int depth, java.util.function.Supplier<JsonElement> body) {
		if (!stack.add(o)) {
			return new JsonPrimitive("<cycle> " + o.getClass().getSimpleName());
		}
		try {
			return body.get();
		} finally {
			stack.remove(o);
		}
	}

	private JsonElement fields(Object o, int depth) {
		JsonObject obj = new JsonObject();
		for (Field field : fieldsOf(o.getClass())) {
			JsonElement v;
			try {
				v = value(field.get(o), depth);
			} catch (Throwable t) {
				v = new JsonPrimitive("<error> " + t);
			}
			obj.add(field.getName(), v);
		}
		return obj;
	}

	private JsonElement component(Component c) {
		JsonObject obj = new JsonObject();
		obj.addProperty("text", c.getString());
		obj.add("json", ComponentSerialization.CODEC.encodeStart(ops, c).result().orElse(JsonNull.INSTANCE));
		return obj;
	}

	private JsonElement item(ItemStack stack) {
		if (stack.isEmpty()) {
			return JsonNull.INSTANCE;
		}
		JsonObject obj = new JsonObject();
		obj.addProperty("name", stack.getHoverName().getString());
		ItemLore lore = stack.get(DataComponents.LORE);
		if (lore != null) {
			JsonArray lines = new JsonArray();
			lore.lines().forEach(line -> lines.add(line.getString()));
			obj.add("lore", lines);
		}
		obj.add("stack", ItemStack.CODEC.encodeStart(ops, stack).result().orElse(new JsonPrimitive(stack.toString())));
		return obj;
	}

	private JsonElement array(Object arr, int depth) {
		int len = Array.getLength(arr);
		Class<?> component = arr.getClass().getComponentType();
		if (component.isPrimitive() && len > MAX_INLINE_ARRAY) {
			return summary(component.getName() + "[]", len);
		}
		JsonArray out = new JsonArray();
		for (int i = 0; i < Math.min(len, MAX_ELEMENTS); i++) {
			out.add(value(Array.get(arr, i), depth + 1));
		}
		if (len > MAX_ELEMENTS) out.add("<" + (len - MAX_ELEMENTS) + " more>");
		return out;
	}

	private JsonElement iterable(Iterable<?> it, int depth) {
		JsonArray out = new JsonArray();
		int i = 0;
		for (Object element : it) {
			if (i++ >= MAX_ELEMENTS) {
				out.add("<more>");
				break;
			}
			out.add(value(element, depth + 1));
		}
		return out;
	}

	private JsonElement map(Map<?, ?> map, int depth) {
		JsonArray out = new JsonArray();
		int i = 0;
		for (Map.Entry<?, ?> entry : map.entrySet()) {
			if (i++ >= MAX_ELEMENTS) {
				out.add("<more>");
				break;
			}
			JsonObject pair = new JsonObject();
			pair.add("key", value(entry.getKey(), depth + 1));
			pair.add("value", value(entry.getValue(), depth + 1));
			out.add(pair);
		}
		return out;
	}

	private static JsonPrimitive registryId(Identifier id, Object o) {
		return new JsonPrimitive(id != null ? id.toString() : safeToString(o));
	}

	private static JsonObject summary(String kind, int length) {
		JsonObject obj = new JsonObject();
		obj.addProperty("omitted", kind);
		obj.addProperty("length", length);
		return obj;
	}

	/** JDK and library internals are not worth reflecting into. */
	private static boolean isOpaque(Class<?> cls) {
		String name = cls.getName();
		return name.startsWith("java.") || name.startsWith("javax.") || name.startsWith("jdk.") || name.startsWith("sun.")
			|| name.startsWith("io.netty.") || name.startsWith("com.google.") || name.startsWith("com.mojang.authlib.")
			|| name.startsWith("org.joml.");
	}

	private static List<Field> fieldsOf(Class<?> cls) {
		return FIELD_CACHE.computeIfAbsent(cls, c -> {
			List<Field> out = new ArrayList<>();
			for (Class<?> k = c; k != null && k != Object.class && k != Record.class && !isOpaque(k); k = k.getSuperclass()) {
				for (Field f : k.getDeclaredFields()) {
					if (Modifier.isStatic(f.getModifiers())) continue;
					try {
						f.setAccessible(true);
						out.add(f);
					} catch (RuntimeException ignored) {
					}
				}
			}
			return out;
		});
	}

	private static String safeToString(Object o) {
		try {
			return String.valueOf(o);
		} catch (Throwable t) {
			return "<toString failed> " + o.getClass().getName();
		}
	}

	/** Registry-aware ops let item components (lore, custom_data, ...) encode fully once in game. */
	private static synchronized DynamicOps<JsonElement> ops() {
		ClientPacketListener listener = Minecraft.getInstance().getConnection();
		RegistryAccess registries = listener == null ? null : listener.registryAccess();
		if (registries != cachedRegistries) {
			cachedRegistries = registries;
			cachedOps = registries == null ? JsonOps.INSTANCE : RegistryOps.create(JsonOps.INSTANCE, registries);
		}
		return cachedOps;
	}
}
