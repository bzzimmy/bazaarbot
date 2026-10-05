package com.bazaarbot.mixin;

import net.minecraft.client.gui.screens.inventory.AbstractSignEditScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/** Lets the bridge fill in sign lines before closing the editor. */
@Mixin(AbstractSignEditScreen.class)
public interface SignEditScreenAccessor {
	@Accessor("messages")
	String[] bazaarbot$getMessages();
}
