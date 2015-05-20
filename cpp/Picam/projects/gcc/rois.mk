################################################################################
# Project-Specific Variables
################################################################################
PROJECT := rois
#-------------------------------------------------------------------------------
SO_PICAM := picam
#-------------------------------------------------------------------------------
SRC_DIR := ../../../samples/source\ code/platform\ independent
INC_DIR := ../../../includes
#-------------------------------------------------------------------------------
WARN := -Wall -Wextra -Werror -ansi -pedantic-errors
################################################################################

################################################################################
# Space Tranformation
################################################################################
SPACE :=
SPACE +=
#-------------------------------------------------------------------------------
s+ = $(subst \$(SPACE),+,$1)
+s = $(subst +,\$(SPACE),$1)
+? = $(subst +,?,$1)
#-------------------------------------------------------------------------------
SRC_DIR := $(call s+,$(SRC_DIR))
################################################################################

################################################################################
# Debug-Specific Variables
################################################################################
ifdef NDEBUG
    DEBUG   := -O3 -DNDEBUG
    DBG_DIR := release
else
    DEBUG   := -g
    DBG_DIR := debug
endif
################################################################################

################################################################################
# Standard Make Variables
################################################################################
CXX      := g++
CXXFLAGS := $(WARN) $(DEBUG) -c -pthread
#-------------------------------------------------------------------------------
LDFLAGS := $(WARN) $(DEBUG) -pthread
################################################################################

################################################################################
# Standard PI Variables
################################################################################
INT_DIR := objlin/x86_64/$(DBG_DIR)
#-------------------------------------------------------------------------------
OUT_DIR ?= $(INT_DIR)
OUTPUT  := $(OUT_DIR)/$(PROJECT)
#-------------------------------------------------------------------------------
SRC := $(SRC_DIR)/$(PROJECT).cpp
INC := -I$(call +s,$(SRC_DIR)) $(addprefix -I, $(INC_DIR))
DEP := $(patsubst $(SRC_DIR)/%.cpp, $(INT_DIR)/%.d, $(SRC))
OBJ := $(patsubst $(SRC_DIR)/%.cpp, $(INT_DIR)/%.o, $(SRC))
LNK := $(addprefix -l, $(SO_PICAM))
DIR := $(sort $(INT_DIR) $(OUT_DIR))
################################################################################

.PHONY: all checkdirs clean

all: checkdirs $(OUTPUT)
	@:

-include $(DEP)

$(OUTPUT): $(OBJ)
	@echo Creating $(@F)
	@$(CXX) $(LDFLAGS) -o $@ $(OBJ) $(LNK)

$(INT_DIR)/%.o: $(call +?,$(SRC_DIR))/%.cpp
	@echo Compiling $(lastword $(<F))
	@$(CXX) $(CXXFLAGS) $(INC) -Wp,-MMD,$(INT_DIR)/$*.$$$$ -o $@ "$<"; \
		sed 's,\($*\)\.o[ :]*,$(INT_DIR)/\1.o $(INT_DIR)/$*.d : ,g' \
			< $(INT_DIR)/$*.$$$$ \
			> $(INT_DIR)/$*.d; \
		rm -f $(INT_DIR)/$*.$$$$

checkdirs: $(DIR)

$(DIR):
	@mkdir -p $@

clean:
	@echo Cleaning $(PROJECT)
	@rm -f -r $(INT_DIR)
	@rm -f $(OUTPUT)
